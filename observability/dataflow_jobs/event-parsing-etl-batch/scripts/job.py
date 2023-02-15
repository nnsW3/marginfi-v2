import argparse
import logging
import json
import types
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict, Union
from pathlib import Path
from anchorpy import Idl, Program, EventParser, Event
from attr import dataclass
from solders.pubkey import Pubkey
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions

# Defines the BigQuery schema for the output table.
PROCESSED_TRANSACTION_SCHEMA = ",".join(
    [
        "id:STRING",
        "timestamp:TIMESTAMP",
        "signature:STRING",
        "signer:STRING",
        "indexing_address:STRING",
        "fee:BIGNUMERIC",
    ]
)

LENDING_ACCOUNT_DEPOSIT_EVENT = 'LendingAccountDepositEvent'
LENDING_ACCOUNT_WITHDRAW_EVENT = 'LendingAccountWithdrawEvent'
LENDING_ACCOUNT_BORROW_EVENT = 'LendingAccountBorrowEvent'
LENDING_ACCOUNT_REPAY_EVENT = 'LendingAccountRepayEvent'
MARGINFI_ACCOUNT_CREATE_EVENT = 'MarginfiAccountCreateEvent'


@dataclass
class LiquidityChangeRecord:
    NAME = "LiquidityChange"

    version: str
    marginfi_group: Pubkey
    marginfi_account: Pubkey
    authority: Pubkey
    operation: str
    amount: int
    balance_closed: bool

    @staticmethod
    def from_event(event: Event) -> "LiquidityChangeRecord":
        balance_closed = None
        if event.name == LENDING_ACCOUNT_REPAY_EVENT or event.name == LENDING_ACCOUNT_WITHDRAW_EVENT:
            balance_closed = event.data.close_balance

        return LiquidityChangeRecord(operation=event.name,
                                     version=event.data.header.version,
                                     marginfi_account=event.data.header.marginfi_account,
                                     marginfi_group=event.data.header.marginfi_group,
                                     authority=event.data.header.signer,
                                     amount=event.data.amount,
                                     balance_closed=balance_closed)


@dataclass
class MarginfiAccountCreationRecord:
    NAME = "MarginfiAccountCreation"

    version: str
    marginfi_group: Pubkey
    marginfi_account: Pubkey
    authority: Pubkey

    @staticmethod
    def from_event(event: Event) -> "MarginfiAccountCreationRecord":
        return MarginfiAccountCreationRecord(version=event.data.header.version,
                                             marginfi_account=event.data.header.marginfi_account,
                                             marginfi_group=event.data.header.marginfi_group,
                                             authority=event.data.header.signer)


Record = Union[LiquidityChangeRecord, MarginfiAccountCreationRecord]


def is_liquidity_change_event(event_name: str) -> bool:
    return event_name in [
        LENDING_ACCOUNT_DEPOSIT_EVENT,
        LENDING_ACCOUNT_WITHDRAW_EVENT,
        LENDING_ACCOUNT_BORROW_EVENT,
        LENDING_ACCOUNT_REPAY_EVENT,
    ]


def event_to_record(event: Event) -> Optional[Record]:
    if is_liquidity_change_event(event.name):
        return LiquidityChangeRecord.from_event(event)
    elif event.name == MARGINFI_ACCOUNT_CREATE_EVENT:
        return MarginfiAccountCreationRecord.from_event(event)
    else:
        print("discarding unsupported event:", event.name)
        return None


def process_event(record_list: List[Record], event: Event) -> None:
    maybe_record = event_to_record(event)
    if maybe_record is not None:
        record_list.append(maybe_record)


class DispatchEventsDoFn(beam.DoFn):
    def process(self, record: Record, *args, **kwargs):
        yield beam.pvalue.TaggedOutput(record.NAME, record)


def run(
        input_table: str,
        target_dataset: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        beam_args: List[str] = None,
) -> None:
    path = Path("marginfi.json")
    raw = path.read_text()

    def extract_events_from_tx(tx):
        idl = Idl.from_json(raw)
        indexed_program = tx["indexing_address"]
        program = Program(idl, Pubkey.from_string(indexed_program))
        event_parser = EventParser(program.program_id, program.coder)
        # instruction_coder = program.coder.instruction
        # program_ixs = [instruction_coder.parse(raw_ix) for raw_ix in tx[""]]
        meta = json.loads(tx["meta"], object_hook=lambda d: types.SimpleNamespace(**d))

        records_list: List[Record] = []
        event_parser.parse_logs(meta.logMessages, lambda event: process_event(records_list, event))
        return records_list

    """Build and run the pipeline."""
    pipeline_options = PipelineOptions(beam_args, save_main_session=True)

    if start_date is not None and end_date is not None:
        input_query = f'SELECT * FROM `{input_table}` WHERE DATE(timestamp) >= "{start_date}" AND DATE(timestamp) < "{end_date}"'
    elif start_date is not None:
        input_query = (
            f'SELECT * FROM `{input_table}` WHERE DATE(timestamp) >= "{start_date}"'
        )
    elif end_date is not None:
        input_query = (
            f'SELECT * FROM `{input_table}` WHERE DATE(timestamp) < "{end_date}"'
        )
    else:
        input_query = f"SELECT * FROM `{input_table}`"

    with beam.Pipeline(options=pipeline_options) as pipeline:
        # Define steps
        read_raw_txs = beam.io.ReadFromBigQuery(query=input_query, use_standard_sql=True)

        extract_events = beam.FlatMap(extract_events_from_tx)

        dispatch_events = beam.ParDo(DispatchEventsDoFn()).with_outputs(
            LiquidityChangeRecord.NAME,
            MarginfiAccountCreationRecord.NAME,
        )

        if target_dataset == "local_file":  # For testing purposes
            write_liquidity_change_events = beam.io.WriteToText("local_file_liquidity_change_events")
            write_marginfi_account_creation_events = beam.io.WriteToText("local_file_marginfi_account_creation_events")
        else:
            print("TODOOOOO")
            exit(1)
            # write_liquidity_change_events = beam.io.WriteToBigQuery(
            #     output_table,
            #     schema=PROCESSED_TRANSACTION_SCHEMA,
            #     write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
            # )

        # Define pipeline
        tagged_events = (
                pipeline
                | "ReadRawTxs" >> read_raw_txs
                | "ExtractEvents" >> extract_events
                | "DispatchEvents" >> dispatch_events
        )

        tagged_events[LiquidityChangeRecord.NAME] | "WriteLiquidityChangeEvent" >> write_liquidity_change_events
        tagged_events[MarginfiAccountCreationRecord.NAME] | "WriteMarginfiAccountCreationEvent" >> write_marginfi_account_creation_events


def main():
    logging.getLogger().setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_table",
        type=str,
        required=True,
        help="Input BigQuery table specified as: "
             "PROJECT:DATASET.TABLE or DATASET.TABLE.",
    )
    parser.add_argument(
        "--target_dataset",
        type=str,
        required=True,
        help="Output BigQuery dataset where event tables are located: PROJECT:DATASET",
    )
    parser.add_argument(
        "--start_date",
        type=str,
        help="Start date to consider (inclusive) as: YYYY-MM-DD",
    )
    parser.add_argument(
        "--end_date",
        type=str,
        help="End date to consider (exclusive) as: YYYY-MM-DD",
    )
    known_args, remaining_args = parser.parse_known_args()

    run(
        input_table=known_args.input_table,
        target_dataset=known_args.target_dataset,
        start_date=known_args.start_date,
        end_date=known_args.end_date,
        beam_args=remaining_args,
    )


if __name__ == "__main__":
    main()
