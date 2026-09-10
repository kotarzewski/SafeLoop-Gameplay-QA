# Security policy

SafeLoop Gameplay QA is designed around least privilege, but executing a game always executes project code.

Do not run untrusted projects with runtime enabled. Keep `SAFELOOP_QA_ALLOW_RUNTIME=0` until `scan_runtime_risks` has been reviewed.

Never place API keys or credentials in SafeLoop environment variables. SafeLoop does not need them.

Report security issues privately to the repository owner rather than publishing exploit details in a public issue before a fix is available.
