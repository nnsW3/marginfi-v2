use crate::{
    constants::{CAMPAIGN_AUTH_SEED, CAMPAIGN_SEED},
    state::Campaign,
};
use anchor_lang::prelude::*;
use anchor_spl::token::{transfer, Token, TokenAccount, Transfer};
use marginfi::state::marginfi_group::Bank;
use std::mem::size_of;

pub fn process(
    ctx: Context<CreateCampaign>,
    lockup_period: u64,
    max_deposits: u64,
    max_rewards: u64,
) -> Result<()> {
    transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.funding_account.to_account_info(),
                to: ctx.accounts.campaign_reward_vault.to_account_info(),
                authority: ctx.accounts.admin.to_account_info(),
            },
        ),
        max_rewards,
    )?;

    *ctx.accounts.campaign = Campaign {
        admin: ctx.accounts.admin.key(),
        lockup_period,
        active: true,
        max_deposits,
        remaining_capacity: max_deposits,
        max_rewards,
        marginfi_bank_pk: ctx.accounts.marginfi_bank.key(),
    };

    msg!("Created campaing\n{:?}", ctx.accounts.campaign);

    Ok(())
}

#[derive(Accounts)]
pub struct CreateCampaign<'info> {
    #[account(
        init,
        payer = admin,
        space = size_of::<Campaign>() + 8,
    )]
    pub campaign: Account<'info, Campaign>,
    #[account(
        init,
        payer = admin,
        token::mint = asset_mint,
        token::authority = campaign_reward_vault_authority,
        seeds = [
            CAMPAIGN_SEED.as_bytes(),
            campaign.key().as_ref(),
        ],
        bump,
    )]
    pub campaign_reward_vault: Account<'info, TokenAccount>,
    #[account(
        seeds = [
            CAMPAIGN_AUTH_SEED.as_bytes(),
            campaign.key().as_ref(),
        ],
        bump,
    )]
    /// CHECK: Asserted by PDA derivation
    pub campaign_reward_vault_authority: AccountInfo<'info>,
    #[account(
        address = marginfi_bank.load()?.mint,
    )]
    /// CHECK: Asserted by constraint
    pub asset_mint: AccountInfo<'info>,
    pub marginfi_bank: AccountLoader<'info, Bank>,
    #[account(mut)]
    pub admin: Signer<'info>,
    /// CHECK: Asserted by token check
    #[account(mut)]
    pub funding_account: AccountInfo<'info>,
    pub rent: Sysvar<'info, Rent>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}
