# Arbitrage Radar v0.5.1

Главное обновление:
- отдельный LIVE-движок классического межбиржевого арбитража;
- Bybit Spot WebSocket;
- OKX BBO WebSocket;
- KuCoin Spot BBO WebSocket;
- MEXC оптимизированный 1-секундный REST fallback (текущий официальный WS bookTicker у MEXC использует Protobuf);
- таблица UI обновляется по умолчанию каждые 250 мс;
- Age: возраст самой старой котировки из двух ног;
- Живёт: сколько непрерывно держится сигнал выше минимального NET edge;
- Ask qty / Bid qty: объём на лучшей цене;
- отдельный понятный столбец "ЧТО ДЕЛАТЬ" на Classic, Funding и Basis;
- API бирж хранятся локально через Windows/system keyring;
- проверка READ-доступа и балансов Bybit / OKX / MEXC / KuCoin.

ВАЖНО ПРО LIVE TRADING
v0.5 специально НЕ отправляет реальные ордера.
Execution Engine уже выделен отдельным модулем, но submit_live_orders аппаратно заблокирован.
Сначала:
1. подключить API с Read permission;
2. убедиться, что все 4 баланса читаются;
3. внести реальные taker fees;
4. проверить размеры/точность ордеров и реальную глубину;
5. затем активировать торговое исполнение.

НИКОГДА не выдавайте API-ключу разрешение Withdraw.

Установка из v0.4:
Обновления → выбрать ArbitrageRadar_v0.5_Update.zip
После обновления установщик при необходимости добавит websocket-client.


## Hotfix 0.5.1
- Исправлен аварийный запуск Funding Arbitrage: `Opportunity.pnl()` → `Opportunity.net_pnl()`.
- Ошибка фонового funding-refresh теперь не должна закрывать приложение.
