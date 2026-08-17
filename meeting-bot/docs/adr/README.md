# Architecture decision records

Decisions whose reasoning is not recoverable from the code. Each records what was
decided, what it rules out, and what would justify revisiting it.

Not every choice needs one. These are the ones where a reader would otherwise
reasonably ask "why on earth is it like this?".

| # | Decision | Status |
|---|---|---|
| [0001](0001-client-only-websocket.md) | The bot is a WebSocket client, never a server | Accepted |
| [0002](0002-interfaces-from-day-one.md) | Three interfaces exist before their second implementation | Accepted |
| [0003](0003-two-upload-transports.md) | Two upload transports behind one interface | Accepted |
| [0004](0004-runtime-vs-durable-state.md) | Runtime and durable state are separate types | Accepted |
| [0005](0005-caption-reassembly.md) | Captions are reassembled, not accumulated | Accepted |
| [0006](0006-browser-scripts-as-files.md) | Browser JavaScript lives in `.js` files | Accepted |

## Format

Short. Context, decision, consequences, and what would change our mind. If it
runs past a page, it is probably documentation rather than a decision record.
