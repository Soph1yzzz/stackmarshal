# Capability policy

Map every requirement to a capability with status, criticality, acquisition options,
selected option, trust, evidence, verification, fallback, and approval class.

Search in order: existing implementation, installed Skill/MCP/plugin, official or
primary source, established OSS, then custom implementation. Keep categories
separate: reference OSS, Agent Skill, MCP server, Codex plugin, application library,
and external CLI. A discovered capability may list its dependencies, but may not
recursively control discovery. Maximum acquisition discovery depth is one.

Score candidates out of 100: requirement fit 30, maintenance 15, security 15,
architecture 10, license 10, platform 10, integration cost 5, documentation 5.
No license, archived status, platform incompatibility, critical vulnerability,
secret requirement, suspicious install hook, unreviewable binary, inability to pin,
or excessive permissions disqualifies the candidate.
