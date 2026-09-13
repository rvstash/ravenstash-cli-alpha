# Unreleased command and native-credential changes

The canonical group is `rvs art`. Format selectors are `--format/-f` and ORAS's
`--rvs-format`; artifact targets use `--target/-t` on leaf commands. Removed commands:
`artifacts`, `ci`, `upgrade`, `oci-reference`, `art auth print-token`, custom mirror
creation, mirror current/clear, and redundant per-format URL/config commands.

Use `art token mint`, `art endpoint`, `art reference`, and `art native config`.
Maven helper publishing is `art maven publish --group-id ... --artifact-id ...`;
native `rvs mvn deploy` is unchanged. Official mirrors use `art mirror create [SOURCE]`.
Repository upstreams attach caches with `--remote-cache rc_...`; `art mirror list`
prints that immutable reference while the mirror group remains the direct-access surface.
`update --to SERIES` previews; adding `--apply` installs. No transitional aliases
are provided for retired commands.

A native token selects one or more explicit formats on one exact target. ORAS can
use a single host login for Container and Helm. Native setup prints instructions
without minting or writing anything. See the [command reference](command-reference.md).

Multi-format options accept comma-separated values, repeated flags, or both:

```bash
rvs art repo create packages --format pypi,npm,maven,container,helm
rvs art token mint --target platform/packages -f container -f helm
```

Whitespace is trimmed and duplicates are removed. Empty or unknown formats fail
before any mutation. Commands requiring one format still accept only one.
