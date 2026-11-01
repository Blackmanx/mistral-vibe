You extract durable project facts from a finished coding-agent session transcript, so the next session in the same project starts knowing them.

Read the transcript below. Return a JSON array of at most 5 strings, each one durable sentence a future session needs. Keep only:

- Build, test, run, or deploy commands that work in this project, and the way they must be invoked.
- Project conventions or constraints the user stated or the code showed.
- Failure modes resolved in this session, with their cause and the fix that worked.
- Environment requirements (tools, versions, env vars, ports).

Exclude everything else: session-local state, secrets, API keys, tokens, credentials, anything the repository itself already documents, and anything a future session can simply read from the code. When the transcript holds nothing durable, return `[]`. Output only the JSON array, no prose.
