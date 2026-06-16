# Ventra SFTP public keys

These are **public** SSH keys — safe to commit. Ventra generated the two
keypairs on their side and sent us only the public halves (2026-06-15
reply, `Ventra_HHA_PublicKeys.zip`). Ventra keeps the private keys and uses
them to authenticate when they push files **to** HHA's SFTP endpoint. HHA
never holds the private keys and never connects as these users.

| File | SFTP local user | Path | Feed |
|---|---|---|---|
| `ventra-stdspec.pub` | `ventra-stdspec` | `vendor-inbound/ventra/stdspec/` | Standard Data Extract (row-level, PHI; 30-day lifecycle) |
| `ventra-preagg.pub`  | `ventra-preagg`  | `vendor-inbound/ventra/preagg/`  | Pre-aggregated extract (no PHI; 90-day lifecycle) |

The two keys are intentionally distinct so a compromise of one path's key
does not expose the other, and each can be rotated independently.

## Install (deploy)

```powershell
.\scripts\deploy-ventra-sftp.ps1 -ImportKeys "docs\06-vendors\ventra\sftp-keys"
```

`-ImportKeys` copies these `.pub` files into the deploy keydir and skips
keygen, then installs them as the `sshAuthorizedKeys` on the two storage
local users (`infra/modules/vendor_storage.bicep`).

## Rotation

When Ventra rotates a key, they send a new `.pub`; replace the file here,
re-run the deploy with `-ImportKeys`, and the storage local user picks up
the new authorized key. Quarterly cadence per the security model in the
plan. Old `.pub` history stays in git for audit.
