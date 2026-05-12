# 04 — Operations

> **Audience:** On-call engineers, ops, security.
> **Start here at 2 a.m.:** [RUNBOOK.md](RUNBOOK.md) — the canonical incident playbook. Branch to [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for low-severity symptoms or [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) for security-related events.

Day-2 operations: keep the system running, respond when it isn't.

## Contents

- [RUNBOOK.md](RUNBOOK.md) — quick orientation, first-deploy procedure, secret rotation, backup/restore, generic incident playbooks
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — symptom → fix lookup. Local dev failures, Docker, env vars, Azure-side gotchas, deploy issues
- [SECURITY_INCIDENT_PLAYBOOK.md](SECURITY_INCIDENT_PLAYBOOK.md) — security-focused: suspected breach, credential compromise, suspicious audit log, ransomware. Includes the credential-rotation runbooks.

## Severity decision tree

| Symptom | First read |
|---|---|
| Local dev broken | [TROUBLESHOOTING.md § Local dev](TROUBLESHOOTING.md) |
| Deploy failed | [TROUBLESHOOTING.md § Azure / production](TROUBLESHOOTING.md) |
| `/ready` returns 500 in prod | [TROUBLESHOOTING.md § /ready returns 500](TROUBLESHOOTING.md) |
| Postgres connection pool exhausted | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Cert about to expire | [RUNBOOK.md § Incident playbooks](RUNBOOK.md) |
| Suspected PHI breach | [SECURITY_INCIDENT_PLAYBOOK.md § Scenario 1](SECURITY_INCIDENT_PLAYBOOK.md) — escalate immediately |
| Credential compromise | [SECURITY_INCIDENT_PLAYBOOK.md § Scenario 2](SECURITY_INCIDENT_PLAYBOOK.md) |
| Lost / stolen device | [SECURITY_INCIDENT_PLAYBOOK.md § Scenario 6](SECURITY_INCIDENT_PLAYBOOK.md) |

## Related folders

- [../02-architecture/adr/004-backup-and-disaster-recovery.md](../02-architecture/adr/004-backup-and-disaster-recovery.md) — the formal RTO/RPO commitments
- [../01-leadership/COMPLIANCE_POSTURE.md](../01-leadership/COMPLIANCE_POSTURE.md) — incident reporting obligations under HIPAA

---

*Back to [docs/README.md](../README.md) for the full doc map.*
