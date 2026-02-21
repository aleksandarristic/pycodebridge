# TODO (Public)

Current status:

- Add a global output chunking boundary wrapper.
  - Introduce a transport-agnostic sink wrapper that enforces max message length for every outbound `send`, regardless of caller path.
  - Apply it at the outer sink boundary so direct `sink.send(...)` calls cannot bypass chunking in either DMs or repo channels.
  - Preserve existing wrapper behavior (thread/reply context, lock-state emoji, repo-prefix formatting) while enforcing post-prefix length limits.
  - Add integration coverage demonstrating that oversized outputs are safely split across both DM and channel flows.
