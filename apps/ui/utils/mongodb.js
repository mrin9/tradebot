import { MongoClient } from 'mongodb';

const uri = import.meta.env.MONGODB_URI || 'mongodb://localhost:27017';
const dbName = import.meta.env.DB_NAME || 'stock_data';

let client;
let clientPromise;

if (!client) {
    client = new MongoClient(uri);
    clientPromise = client.connect();
}

export async function getDb() {
    const connectedClient = await clientPromise;
    return connectedClient.db(dbName);
}

export const collections = {
    NIFTY_TICKS: 'nifty_candle',
    OPTIONS_TICKS: 'options_candle',
    ACTIVE_CONTRACTS: 'active_contract',
    INSTRUMENT_MASTER: 'instrument_master'
};
