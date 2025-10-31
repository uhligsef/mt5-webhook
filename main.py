from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

# Einfaches Log für Trades
trades = []

@app.route('/', methods=['GET'])
def test():
    action = request.args.get('action', '')
    
    if action == 'test':
        return jsonify({
            "status": "OK",
            "message": "Verbindung erfolgreich",
            "timestamp": datetime.now().isoformat()
        })
    
    return jsonify({
        "status": "OK",
        "message": "MT5 Webhook Server läuft",
        "trades_count": len(trades)
    })

@app.route('/', methods=['POST'])
def add_trade():
    try:
        data = request.get_json()
        
        if data.get('action') == 'add_manual_trade':
            # Trade zu Liste hinzufügen
            trade_info = {
                "ticket": data.get('ticket'),
                "symbol": data.get('symbol'),
                "side": data.get('side'),
                "price": data.get('price'),
                "volume": data.get('volume'),
                "timestamp": datetime.now().isoformat()
            }
            trades.append(trade_info)
            
            print(f"✅ Trade empfangen: Ticket {trade_info['ticket']}, {trade_info['symbol']} {trade_info['side']}")
            
            return jsonify({
                "ok": True,
                "message": "Trade erfolgreich hinzugefügt",
                "trade": trade_info
            })
        else:
            return jsonify({"error": "Unbekannte Aktion"}), 400
            
    except Exception as e:
        print(f"❌ Fehler: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/trades', methods=['GET'])
def get_trades():
    return jsonify({
        "trades": trades,
        "count": len(trades)
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)