use {
    anchor_client::{Client, Cluster, Program},
    clap::Parser,
    serde::{Deserialize, Serialize},
    solana_sdk::{
        commitment_config::CommitmentConfig,
        pubkey::Pubkey,
        signature::{Keypair, Signer},
    },
    std::str::FromStr,
};

#[derive(Default, Debug, Parser)]
pub struct GlobalOptions {
    // /// Cluster override.
    // #[clap(global = true, long = "cluster")]
    // pub cluster: Option<Cluster>,
    // /// Wallet override.
    // #[clap(global = true, long = "wallet")]
    // pub wallet: Option<WalletPath>,
    // /// Program ID override.
    // #[clap(global = true, long = "pid")]
    // pub pid: Option<Pubkey>,
    // /// Commitment.
    // #[clap(global = true, long = "commitment")]
    // pub commitment: Option<CommitmentLevel>,
    /// Dry run for any transactions involved.
    #[clap(global = true, long = "dry-run", action, default_value_t = false)]
    pub dry_run: bool,

    #[clap(
        global = true,
        long = "skip-confirmation",
        short = 'y',
        action,
        default_value_t = false
    )]
    pub skip_confirmation: bool,
}

#[derive(Copy, Clone, Debug)]
pub enum TxMode {
    DryRun,
    Multisig,
    Normal,
}

pub struct Config {
    pub cluster: Cluster,
    pub fee_payer: Keypair,
    pub multisig: Option<Pubkey>,
    pub program_id: Pubkey,
    pub commitment: CommitmentConfig,
    pub dry_run: bool,
    pub client: Client,
    pub mfi_program: Program,
    pub lip_program: Program,
}

impl Config {
    /// Use this only for transations that have a separate fee payer and authority.
    pub fn explicit_fee_payer(&self) -> Pubkey {
        self.fee_payer.pubkey()
    }

    /// Either the fee payer or the multisig authority.
    pub fn authority(&self) -> Pubkey {
        if let Some(multisig) = &self.multisig {
            *multisig
        } else {
            self.fee_payer.pubkey()
        }
    }

    pub fn get_tx_mode(&self) -> TxMode {
        if self.dry_run {
            TxMode::DryRun
        } else if self.multisig.is_some() {
            TxMode::Multisig
        } else {
            TxMode::Normal
        }
    }

    pub fn get_signers(&self, explicit_fee_payer: bool) -> Vec<&Keypair> {
        if explicit_fee_payer || self.multisig.is_none() {
            vec![&self.fee_payer]
        } else {
            vec![]
        }
    }

    /// Get the authority keypair for signing transactions.
    /// This errors if the authority is a multisig.
    pub fn get_non_ms_authority_keypair(&self) -> anyhow::Result<&Keypair> {
        if self.multisig.is_none() {
            Ok(&self.fee_payer)
        } else {
            Err(anyhow::anyhow!("Cannot get authority keypair for multisig"))
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountEntry {
    // Base58 pubkey string.
    pub address: String,
    // Name of JSON file containing the account data.
    pub filename: String,
}

crate::home_path!(WalletPath, ".config/solana/id.json");
