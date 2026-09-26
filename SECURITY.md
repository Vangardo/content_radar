# Security policy

## Supported versions

Pre-1.0 single-owner application. Fixes target the latest 0.1.x release and main;
older releases are not maintained separately. No independent security audit has
been performed. A passing scanner is not a security guarantee.

## Report privately

Use [GitHub private vulnerability reporting](https://github.com/Vangardo/content_radar/security/advisories/new).
Do not open public issues with exploit details, credentials or personal data.
Include version, reproduction steps with synthetic data, impact and any proposed fix.
Never send a live database or active API key.

## Deployment boundary

- Use server mode and HTTPS remotely; local mode is loopback-only.
- Generate your own strong password and server secret. Demo credentials are only for fixtures.
- Passwords use scrypt; server API keys use authenticated Fernet encryption.
  The encryption key lives outside SQLite in a read-only mounted secret.
- Local Windows installations use Windows Credential Manager for YouTube keys.
- Session cookies are HttpOnly, SameSite=Strict and Secure in server mode.
  CSRF, trusted-host checks, input limits and login rate limiting are enabled.
- API tokens are scoped, revocable and stored as hashes. Prefer read-only access.
- Protect the host, backups, browser session and proxy configuration. Anyone who can
  read both encrypted data and the server secret can recover saved keys.
- One administrator and one process per SQLite. Multi-user isolation is not supported.

## Supply chain and data

CI uses commit-pinned Actions, minimum token permissions, secret scanning and a Python
dependency audit. Dependabot checks Actions, container and Python dependencies.
Release images include OCI source/revision metadata, SBOM and build provenance.
Only allowlisted runtime paths enter the Docker build context. Keep data, secrets,
SSH files, backups and private reports outside Git and published artifacts.

API data expires after 28 days. Exports and backups are controlled by the operator
and need their own retention policy. Use synthetic data in examples and issues.

If a secret leaks, revoke or rotate it at its issuer immediately. Removing it from
the latest commit neither revokes it nor removes it from history.
