from flask import Flask, request, jsonify
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

app = Flask(__name__)

# Deaktiviere Komprimierung global
app.config['COMPRESS_REGISTER'] = False

# Google Sheets Setup
def get_google_sheet():
    try:
        # Service Account Credentials aus Environment Variable
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not creds_json:
            print("❌ GOOGLE_CREDENTIALS nicht gefunden!")
            return None
            
        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Öffne dein Sheet
        sheet_url = os.environ.get('SHEET_URL')
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet('Tagebuch')
        
        return worksheet
    except Exception as e:
        print(f"❌ Fehler beim Sheet-Zugriff: {str(e)}")
        return None

@app.route('/', methods=['GET'])
def test():
    action = request.args.get('action', '')
    
    if action == 'test':
        # Teste Sheet-Verbindung
        sheet = get_google_sheet()
        if sheet:
            response = jsonify({
                "status": "OK",
                "message": "Verbindung erfolgreich - Sheet verbunden",
                "timestamp": datetime.now().isoformat()
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response
        else:
            response = jsonify({
                "status": "ERROR",
                "message": "Sheet-Verbindung fehlgeschlagen"
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response, 500
    
    response = jsonify({
        "status": "OK",
        "message": "MT5 Webhook Server läuft"
    })
    response.headers['Content-Encoding'] = 'identity'
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@app.route('/', methods=['POST'])
def add_trade():
    try:
        data = request.get_json()
        
        if data.get('action') == 'add_manual_trade':
            sheet = get_google_sheet()
            if not sheet:
                response = jsonify({"error": "Sheet nicht verfügbar"})
                response.headers['Content-Encoding'] = 'identity'
                return response, 500
            
            ticket = data.get('ticket', '')
            
            # PRÜFE OB TICKET SCHON EXISTIERT
            print(f"🔍 Prüfe ob Ticket {ticket} bereits existiert...")
            all_values = sheet.get_all_values()
            
            for i, row in enumerate(all_values):
                if len(row) > 1 and str(row[1]).strip() == str(ticket).strip():  # Spalte B (Index 1)
                    print(f"⚠️ Ticket {ticket} existiert bereits in Zeile {i+1} - überspringe")
                    response = jsonify({
                        "ok": False,
                        "message": f"Ticket {ticket} existiert bereits",
                        "ticket": ticket,
                        "duplicate": True
                    })
                    response.headers['Content-Encoding'] = 'identity'
                    response.headers['Content-Type'] = 'application/json; charset=utf-8'
                    return response
            
            print(f"✅ Ticket {ticket} ist neu - schreibe ins Sheet")
            
            # Finde nächste freie Zeile
            next_row = len(all_values) + 1
            
            # Daten vorbereiten
            symbol = data.get('symbol', '').lower()
            side = data.get('side', '')
            price = data.get('price', 0)
            volume = data.get('volume', 0)
            balance = data.get('balance', 0)
            timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            # Bestimme ob Krypto oder Forex
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            
            # Schreibe in Sheet (Spalten A-H)
            row_data = [
                timestamp,      # A: Datum/Zeit
                str(ticket),    # B: Ticket
                '',             # C: leer
                symbol,         # D: Symbol
                side,           # E: Side (B/S)
                price,          # F: Entry Price
                0,              # G: TP
                0               # H: SL
            ]
            
            # Schreibe Daten
            sheet.update(f'A{next_row}:H{next_row}', [row_data])
            
            # Setze Status auf EXECUTED (Spalte Y = 25)
            sheet.update(f'Y{next_row}', 'EXECUTED')
            
            # Setze Lots (Spalte V = 22)
            sheet.update(f'V{next_row}', volume)
            
            # Setze Kontostand (W für Krypto, X für Forex)
            if is_crypto:
                sheet.update(f'W{next_row}', balance)
                print(f"  → Krypto Kontostand (W{next_row}): {balance}")
            else:
                sheet.update(f'X{next_row}', balance)
                print(f"  → Forex Kontostand (X{next_row}): {balance}")
            
            print(f"✅ Trade in Zeile {next_row} geschrieben: Ticket {ticket}, {symbol} {side}")
            
            response = jsonify({
                "ok": True,
                "message": "Trade erfolgreich ins Sheet geschrieben",
                "row": next_row,
                "ticket": ticket
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response
        else:
            response = jsonify({"error": "Unbekannte Aktion"})
            response.headers['Content-Encoding'] = 'identity'
            return response, 400
            
    except Exception as e:
        print(f"❌ Fehler: {str(e)}")
        response = jsonify({"error": str(e)})
        response.headers['Content-Encoding'] = 'identity'
        return response, 500

@app.route('/', methods=['PUT'])
def update_trade():
    try:
        data = request.get_json()
        
        if data.get('action') == 'update_trade_exit':
            sheet = get_google_sheet()
            if not sheet:
                response = jsonify({"error": "Sheet nicht verfügbar"})
                response.headers['Content-Encoding'] = 'identity'
                return response, 500
            
            ticket = data.get('ticket', '')
            
            print(f"🔍 Suche Ticket {ticket} zum Aktualisieren...")
            
            # Finde die Zeile mit dem Ticket
            all_values = sheet.get_all_values()
            target_row = None
            
            for i, row in enumerate(all_values):
                if len(row) > 1 and str(row[1]).strip() == str(ticket).strip():  # Spalte B
                    target_row = i + 1  # +1 weil Sheets bei 1 anfängt
                    print(f"✅ Ticket {ticket} gefunden in Zeile {target_row}")
                    break
            
            if not target_row:
                print(f"❌ Ticket {ticket} nicht gefunden")
                response = jsonify({"error": f"Ticket {ticket} nicht gefunden"})
                response.headers['Content-Encoding'] = 'identity'
                return response, 404
            
            # Daten vorbereiten
            symbol = data.get('symbol', '').lower()
            exit_price = data.get('exit_price', 0)
            exit_time = data.get('exit_time', datetime.now().strftime('%d.%m.%Y %H:%M:%S'))
            balance_after = data.get('balance', 0)
            profit = data.get('profit', 0)
            
            # Bestimme ob Krypto oder Forex
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            
            # Update Exit-Zeit (Spalte N = 14)
            sheet.update(f'N{target_row}', exit_time)
            print(f"  → Exit-Zeit (N{target_row}): {exit_time}")
            
            # Update Exit-Preis (Spalte P = 16)
            sheet.update(f'P{target_row}', exit_price)
            print(f"  → Exit-Preis (P{target_row}): {exit_price}")
            
            # Update Kontostand nach Trade (W oder X)
            if is_crypto:
                sheet.update(f'W{target_row}', balance_after)
                print(f"  → Krypto Kontostand nach Trade (W{target_row}): {balance_after}")
            else:
                sheet.update(f'X{target_row}', balance_after)
                print(f"  → Forex Kontostand nach Trade (X{target_row}): {balance_after}")
            
            # Update Status auf CLOSED (Spalte Y = 25)
            sheet.update(f'Y{target_row}', 'CLOSED')
            print(f"  → Status (Y{target_row}): CLOSED")
            
            # Update Gewinn/Verlust (Spalte Z = 26)
            sheet.update(f'Z{target_row}', profit)
            print(f"  → Gewinn/Verlust (Z{target_row}): {profit} €")
            
            print(f"✅ Trade {ticket} erfolgreich aktualisiert in Zeile {target_row}")
            
            response = jsonify({
                "ok": True,
                "message": "Trade erfolgreich aktualisiert",
                "row": target_row,
                "ticket": ticket
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response
        else:
            response = jsonify({"error": "Unbekannte Aktion"})
            response.headers['Content-Encoding'] = 'identity'
            return response, 400
            
    except Exception as e:
        print(f"❌ Fehler: {str(e)}")
        response = jsonify({"error": str(e)})
        response.headers['Content-Encoding'] = 'identity'
        return response, 500

@app.route('/trades', methods=['GET'])
def get_trades():
    try:
        sheet = get_google_sheet()
        if not sheet:
            response = jsonify({"error": "Sheet nicht verfügbar"})
            response.headers['Content-Encoding'] = 'identity'
            return response, 500
        
        all_values = sheet.get_all_values()
        
        response = jsonify({
            "trades": all_values[-10:],  # Letzte 10 Trades
            "count": len(all_values)
        })
        response.headers['Content-Encoding'] = 'identity'
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        response = jsonify({"error": str(e)})
        response.headers['Content-Encoding'] = 'identity'
        return response, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
