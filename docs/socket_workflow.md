# Socket Data Service Workflow

The Trade Bot V2 uses a decoupled architecture for its real-time data streaming:
- **SocketDataService**: The network delivery layer (Socket.IO).
- **SocketDataProvider**: The logic layer (reads DB, generates ticks).
- **CLI**: Controls the background service.

## 1. Connection Details

The Socket.IO server runs alongside the API.

- **Port**: `5050` (Default, configurable via `SOCKET_SIMULATOR_URL` in `packages/config.py`)
- **Path**: `/apimarketdata/socket.io`
- **Transport**: WebSocket / Polling

### JavaScript Client Example
```javascript
import { io } from "socket.io-client";

const socket = io("http://localhost:5050", {
  path: "/apimarketdata/socket.io",
  transports: ["websocket"]
});

socket.on("connect", () => {
  console.log("Connected:", socket.id);
});
```

## 4. Control via CLI

The most reliable way to manage the Socket Data Service is through the CLI.

### Start Service
```bash
python apps/cli/main.py simulator start
```

### Check Status
```bash
python apps/cli/main.py simulator status
```

### Stop Service
```bash
python apps/cli/main.py simulator stop
```

---

---

## 5. Controlling the Stream (Events)

Once the service is running, you can start a specific data replay by sending a socket event.

### Event: `start_simulation`
**Payload:**
```json
{
  "instrument_id": 26000,       // Optional. If omitted/null, streams all instruments.
  "start": "2026-02-18T09:15:00",
  "end": "2026-02-18T15:30:00",
  "delay": 0.01,                // Delay in seconds between emissions. 0 = Max speed.
  "mode": "tick"                // "tick" (default) or "candle"
}
```

#### Mode Breakdown
- **`tick`**: Decomposes 1-minute historical bars into 4 individual price points (Open, High, Low, Close) to simulate real-time volatility.
    - Emits event: `1501-json-full` (Touchline)
    - Data Shape: See **Section 6** below.
- **`candle`**: Sends the 1-minute historical bar as a single aggregate message.
    - Emits event: `1505-json-full` (BarData)
    - Data Shape: See **Section 6** below.

#### Delay Behavior
- **Tick Mode**: The delay is applied between *each* of the 4 sub-ticks (O -> H -> L -> C).
- **Candle Mode**: The delay is applied between each 1-minute bar.
- **Value 0**: Runs the stream as fast as possible (useful for rapid offline backtesting).

### Event: `stop_simulation`
**Payload:** `{}`

---

## 6. Data Shapes (Real-time Events)

The service mimics the XTS API message structure.

### `1501-json-full` (Touchline / Tick)
Used in `mode: "tick"`.

```json
{
  "ExchangeInstrumentID": 26000,
  "Touchline": {
    "LastTradedPrice": 24500.50,
    "LastTradedQuantity": 50,
    "LastTradedTime": 1700000000,
    "TotalTradedQuantity": 100000,
    "Open": 0.0, "High": 0.0, "Low": 0.0, "Close": 0.0, "PercentChange": 0.0
  }
}
```

### `1505-json-full` (BarData / Candle)
Used in `mode: "candle"`.

```json
{
  "ExchangeInstrumentID": 26000,
  "BarData": {
    "Open": 24500.0,
    "High": 24550.0,
    "Low": 24450.0,
    "Close": 24510.0,
    "Volume": 5000,
    "Timestamp": 1700000000
  }
}
```

### `simulation_complete`
Emitted when the requested time range has been fully replayed.

```json
{ "status": "done" }
```
