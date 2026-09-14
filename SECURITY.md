# Security policy

## Supported versions

Security fixes are made for the latest patch of each release series marked
`supported` in Ravenstash's signed channel manifest. Unsupported series may not
receive fixes. Upgrade to a supported series before reporting a version-specific
problem when practical.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use
[GitHub private vulnerability reporting](https://github.com/rvstash/ravenstash-cli-alpha/security/advisories/new)
and include:

- the affected rvs version and operating system;
- a minimal reproduction or proof of concept;
- the impact you observed or expect; and
- any suggested mitigation, if known.

Do not include real Ravenstash credentials, tokens, private package contents, or
customer data. Use synthetic values and redact logs before attaching them.

Maintainers will acknowledge the report, investigate it privately, and
coordinate disclosure and a fixed release. Please allow a reasonable remediation
window before publishing details.

## Scope

This policy covers this CLI, its installers, and release artifacts. For account,
billing, hosted-service, or abuse concerns, follow [SUPPORT.md](SUPPORT.md).
