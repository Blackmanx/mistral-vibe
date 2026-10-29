Classify the user's request for a coding agent.

Return ONLY a JSON object, no markdown or explanation:

{"task": true, "complex": false}

- "task" is true when the user asks for work that may change code, files, or the running system.
- "task" is false for greetings, questions about the conversation, explanations, and requests that are only conversation.
- "complex" is true when the work needs a plan: multiple files, a refactor, a feature, debugging with uncertain cause, or several verification steps.
- "complex" is false for a single small edit, a read-only lookup, or a question.
