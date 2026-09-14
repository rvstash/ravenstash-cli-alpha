# Unreleased command and native-credential changes

The canonical group is `rvs art`. Format selectors are `--format/-f`; ORAS has
no Ravenstash format flag because its manifest determines the OCI content type.
Artifact targets use `--target/-t` on leaf commands. Removed commands:
`artifacts`, `ci`, `upgrade`, `oci-reference`, `art auth print-token`, custom mirror
creation, mirror current/clear, and redundant per-format URL/config commands.
The experimental `art install` command and `art pypi|npm|maven install|publish`
groups are also removed; use the native `rvs pip|uv|twine|npm|mvn` passthroughs.
Package lifecycle management keeps registry-native semantics: `art package
yank|unyank` supports PyPI, while `art package deprecate|undeprecate` supports
npm deprecation messages. Package details show the applicable state and reason.

Use `art token mint`, `art endpoint`, `art reference`, and `art native config`.
Native `rvs mvn deploy` remains available. Official mirrors use `art mirror create [SOURCE]`.
Repository upstreams attach caches with `--remote-cache rc_...`; `art mirror list`
prints that immutable reference while the mirror group remains the direct-access surface.
`update --to SERIES` previews; adding `--apply` installs. No transitional aliases
are provided for retired commands.

A native token selects one or more explicit formats on one exact target. ORAS can
use a single host login for Container and Helm. Native setup prints instructions
without minting or writing anything. See the [command reference](command-reference.md).

Multi-format options accept comma-separated values, repeated flags, or both:

```bash
rvs art repo create packages --format pypi,npm,maven,oci
rvs art token mint --target platform/packages -f pypi -f oci
```

Whitespace is trimmed and duplicates are removed. Empty or unknown formats fail
before any mutation. Commands requiring one format still accept only one.
