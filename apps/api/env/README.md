# Environment variable templates

One template per environment tier from Doc 14 §2 ("Every environment is defined in Terraform.
Environment differences are variables, not separate configurations"). These are **committed
templates with placeholder values only** — never real secrets. Actual values are supplied per
environment as follows:

| Tier | File here | Real values come from |
|---|---|---|
| Local | [`../.env.example`](../.env.example) → copy to `apps/api/.env` | Your own machine (docker-compose) |
| Dev | `.env.dev.example` | GitHub Actions secrets / SSM Parameter Store (Doc 14 §1) |
| QA | `.env.qa.example` | SSM Parameter Store |
| Staging/UAT | `.env.staging.example` | SSM Parameter Store + Secrets Manager |
| Production | `.env.production.example` | AWS Secrets Manager, injected at task startup — never a file on disk (Doc 14 §1, §7) |

DR shares production's variables (it's a warm standby of the same environment, not a distinct
config — Doc 14 §7).

**Local development still uses `apps/api/.env.example`** (copy to `.env`), not a file from this
folder — that one is wired to the docker-compose services in this repo. The templates in this
folder exist so DevOps has one place that documents every variable a real deployment needs, and so
a new environment's Terraform/Secrets Manager setup can be checked against something concrete
instead of reverse-engineered from `hrms/core/config/settings.py` (Pydantic Settings — Document 10
§4, Document 13 §1).

Any real `.env.*` file placed in this folder (as opposed to the committed `.example` templates) is
gitignored — see the root `.gitignore`.
