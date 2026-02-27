import asyncio
import sys
import os
from datetime import datetime

# Ensure we can import from packages
sys.path.append(os.getcwd())

# Import the SocketDataProvider
from packages.simulator.socket_data_provider import SocketDataProvider

# Mock the Socket.IO server to intercept events
class MockSocketServer:
    async def emit(self, event, data):
        # Instead of sending over network, we just process/print the data
        if event == '1501-json-full':
            inst_id = data.get('ExchangeInstrumentID')
            price = data.get('Touchline', {}).get('LastTradedPrice', 'N/A')
            tx_time_ts = data.get('Touchline', {}).get('LastTradedTime', 0)
            print(f"[Tick] ID: {inst_id} | P: {price} | T: {datetime.fromtimestamp(tx_time_ts).strftime('%H:%M:%S')}")
            
        elif event == '1505-json-full':
            inst_id = data.get('ExchangeInstrumentID')
            bar = data.get('BarData', {})
            print(f"[Bar]  ID: {inst_id} | OHLC: {bar['Open']}/{bar['High']}/{bar['Low']}/{bar['Close']} | V: {bar['Volume']}")
            
        elif event == 'simulation_complete':
            print("\n>>> Simulation Complete! <<<")
        else:
            print(f"[{event}] {data}")

async def main():
    mock_sio = MockSocketServer()
    provider = SocketDataProvider(mock_sio)
    
    # TEST 1: All Instruments (Mixed Stream)
    print("=== Test 1: Mixed Stream (All Instruments) ===")
    start_time = datetime(2026, 2, 18, 9, 15)
    end_time = datetime(2026, 2, 18, 9, 20) # Short range for demo
    
    await provider.stream_data(
        instrument_id=None, # None = All
        start_dt=start_time,
        end_dt=end_time,
        delay=0, # Fast replay
        mode='tick'
    )
    
    print("\n" + "="*40 + "\n")
    
    # TEST 2: Single Instrument Candle Mode
    print("=== Test 2: Single Instrument (Candle Mode) ===")
    await provider.stream_data(
        instrument_id=26000, 
        start_dt=start_time,
        end_dt=end_time,
        delay=0, 
        mode='candle'
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
