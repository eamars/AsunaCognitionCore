# Current UI limitations

- The workbench is a local operator interface served through loopback DSH. It is not a public chat interface for channel participants.
- Configured external channel scenes are read-only. A local owner may submit a separately labeled group-speaking prompt only when that group route has an owner configured.
- Historical contexts can be inspected but not sent to. “新上下文” retains the scene's persisted memory; it does not create a new identity or scene.
- The inspector is read-only and reflects the selected scene's current records, not a historical memory snapshot. It shows a bounded recent record set and does not provide full memory editing, pagination, or cross-scene search.
- Preference and group-preference tabs display stored records only. If no structured record exists, the UI shows an empty state instead of deriving one from message text.
- Conversation messages can be loaded from earlier scene sequence pages. The inspector's memory and integration views are bounded and do not expose every database record.
- Live generation is observed through the DSH stream bridge, with persisted state refreshed separately. An observation disconnect does not cancel host work; a send response interruption is not automatically retried.
- The layout is designed for a desktop workbench with a minimum width. Narrow screens may require horizontal scrolling and are not a dedicated mobile layout.
- Provider availability, channel connectivity, action tools, and self-development depend on local host configuration. The UI does not claim that a configured endpoint, running process, or queued message has completed an external operation.
