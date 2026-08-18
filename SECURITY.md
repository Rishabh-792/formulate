# Security Policy

## Supported versions

This is a portfolio/reference project. Security fixes are applied to the
`main` branch only.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via
[GitHub Security Advisories](https://github.com/Rishabh-792/formulate/security/advisories/new)
rather than opening a public issue. I aim to acknowledge reports within 7 days.

## Secrets handling in this repository

Formulate is designed so that **no credential is ever required to run, test, or
demo it**. Concretely:

- The full pipeline runs in a keyless local/mock mode; CI executes the entire
  test suite with no secrets configured.
- `.env` is git-ignored; only `.env.example`, containing empty placeholders,
  is committed.
- Terraform keeps provider API keys out of state where possible and surfaces
  them through Key Vault references; sensitive outputs are marked
  `sensitive = true`.
- No customer, employer, or third-party data appears in this repository. All
  sample documents are fictional.

If you believe you have found a committed secret, please report it privately
using the link above.
