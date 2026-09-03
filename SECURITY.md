# Security

Never commit:
- exchange API keys
- OpenAI API keys
- `settings.json`
- `data/`
- `.venv/`

Exchange API keys should never have withdrawal permission.
Arbitrage Radar stores entered credentials through the operating-system keyring.
