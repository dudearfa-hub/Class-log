from flask import Flask, render_template, request, jsonify, Response, send_file
import csv
import io
import sqlite3
from pathlib import Path
from datetime import date, timedelta

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "classlog.db"

app = Flask(__name__)
app.json.ensure_ascii = False


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seat_row INTEGER NOT NULL,
                seat_col INTEGER NOT NULL,
                UNIQUE(seat_row, seat_col)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                record_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(student_id) REFERENCES students(id)
                    ON DELETE CASCADE
            )
        """)

        # CLASSLOG_UPGRADE_V1: migrasi aman untuk database yang sudah ada.
        record_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(records)")
        }
        if "followup_status" not in record_columns:
            db.execute("""
                ALTER TABLE records
                ADD COLUMN followup_status TEXT NOT NULL
                DEFAULT 'Belum ditindaklanjuti'
            """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        count = db.execute(
            "SELECT COUNT(*) FROM students"
        ).fetchone()[0]

        if count == 0:
            names = [
                "Alya", "Bima", "Citra", "Dafa",
                "Nadia", "Raka", "Fajar", "Salsa",
                "Rizky", "Nisa", "Dion", "Putri",
                "Arif", "Dina", "Rafi", "Zahra",
                "Rian", "Tia", "Farhan", "Lala"
            ]
            db.executemany(
                """INSERT INTO students(name, seat_row, seat_col)
                   VALUES (?, ?, ?)""",
                [
                    (name, i // 4 + 1, i % 4 + 1)
                    for i, name in enumerate(names)
                ]
            )


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/students")
def students():
    with get_db() as db:
        rows = db.execute("""
            SELECT s.id, s.name, s.seat_row, s.seat_col,
                   COUNT(r.id) AS record_count
            FROM students s
            LEFT JOIN records r ON r.student_id = s.id
            GROUP BY s.id
            ORDER BY s.seat_row, s.seat_col
        """).fetchall()
        total_records = db.execute(
            "SELECT COUNT(*) FROM records"
        ).fetchone()[0]
        today_records = db.execute(
            "SELECT COUNT(*) FROM records WHERE record_date = ?",
            (date.today().isoformat(),)
        ).fetchone()[0]

    return jsonify({
        "students": [dict(row) for row in rows],
        "total_records": total_records,
        "today_records": today_records
    })


@app.get("/api/students/<int:student_id>/records")
def student_records(student_id):
    with get_db() as db:
        student = db.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()

        if student is None:
            return jsonify({"error": "Siswa tidak ditemukan"}), 404

        records = db.execute("""
            SELECT * FROM records
            WHERE student_id = ?
            ORDER BY record_date DESC, id DESC
        """, (student_id,)).fetchall()

    return jsonify({
        "student": dict(student),
        "records": [dict(row) for row in records]
    })


@app.post("/api/records")
def add_record():
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    game = str(data.get("game", "")).strip()[:100]
    note = str(data.get("note", "")).strip()[:500]
    record_date = str(data.get("record_date", date.today().isoformat()))

    try:
        date.fromisoformat(record_date)
        student_id = int(student_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Data tanggal atau siswa tidak valid"}), 400

    if not game:
        return jsonify({"error": "Jenis game wajib diisi"}), 400

    with get_db() as db:
        exists = db.execute(
            "SELECT id FROM students WHERE id = ?", (student_id,)
        ).fetchone()

        if not exists:
            return jsonify({"error": "Siswa tidak ditemukan"}), 404

        cursor = db.execute("""
            INSERT INTO records(student_id, game, note, record_date)
            VALUES (?, ?, ?, ?)
        """, (student_id, game, note, record_date))
        record_id = cursor.lastrowid
        student_name = db.execute(
            "SELECT name FROM students WHERE id = ?", (student_id,)
        ).fetchone()["name"]
        db.execute(
            "INSERT INTO audit_log(student_name, action, details) VALUES (?, ?, ?)",
            (student_name, "Catatan ditambahkan", game)
        )

    return jsonify({"success": True, "id": record_id})



@app.put("/api/students/<int:student_id>")
def rename_student(student_id):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:80]

    if not name:
        return jsonify({"error": "Nama siswa wajib diisi"}), 400

    with get_db() as db:
        result = db.execute(
            "UPDATE students SET name = ? WHERE id = ?",
            (name, student_id)
        )
        if result.rowcount == 0:
            return jsonify({"error": "Siswa tidak ditemukan"}), 404

    return jsonify({"success": True, "name": name})



@app.patch("/api/records/<int:record_id>/status")
def update_record_status(record_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()
    allowed = {
        "Belum ditindaklanjuti",
        "Dalam proses",
        "Selesai",
    }
    if status not in allowed:
        return jsonify({"error": "Status tidak valid"}), 400

    with get_db() as db:
        record = db.execute("""
            SELECT r.id, r.game, s.name AS student_name, r.followup_status
            FROM records r JOIN students s ON s.id = r.student_id
            WHERE r.id = ?
        """, (record_id,)).fetchone()
        if record is None:
            return jsonify({"error": "Catatan tidak ditemukan"}), 404

        old_status = record["followup_status"]
        db.execute(
            "UPDATE records SET followup_status = ? WHERE id = ?",
            (status, record_id)
        )
        if old_status != status:
            db.execute("""
                INSERT INTO audit_log(student_name, action, details)
                VALUES (?, ?, ?)
            """, (
                record["student_name"],
                "Status diperbarui",
                f'{record["game"]}: {old_status} → {status}'
            ))

    return jsonify({"success": True, "status": status})


@app.get("/api/audit")
def get_audit_log():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, student_name, action, details, created_at
            FROM audit_log
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()
    return jsonify({"items": [dict(row) for row in rows]})


@app.get("/api/backup")
def download_backup():
    if not DB_PATH.exists():
        return jsonify({"error": "Database belum tersedia"}), 404
    return send_file(
        io.BytesIO(DB_PATH.read_bytes()),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f"classlog-backup-{date.today().isoformat()}.db"
    )


@app.post("/api/layout")
def update_layout():
    data = request.get_json(silent=True) or {}

    try:
        columns = int(data.get("columns", 4))
    except (TypeError, ValueError):
        return jsonify({"error": "Jumlah kolom tidak valid"}), 400

    if not 2 <= columns <= 10:
        return jsonify({"error": "Kolom harus antara 2 dan 10"}), 400

    with get_db() as db:
        rows = db.execute("""
            SELECT id FROM students
            ORDER BY seat_row, seat_col, id
        """).fetchall()

        # Pindahkan sementara agar tidak bentrok dengan UNIQUE seat.
        db.execute("UPDATE students SET seat_row = seat_row + 10000")

        for index, student in enumerate(rows):
            row = index // columns + 1
            col = index % columns + 1
            db.execute("""
                UPDATE students
                SET seat_row = ?, seat_col = ?
                WHERE id = ?
            """, (row, col, student["id"]))

    return jsonify({
        "success": True,
        "columns": columns,
        "rows": (len(rows) + columns - 1) // columns
    })



@app.post("/api/seat/swap")
def swap_seats():
    data = request.get_json(silent=True) or {}
    try:
        first_id = int(data.get("first_id"))
        second_id = int(data.get("second_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "ID kursi tidak valid"}), 400

    if first_id == second_id:
        return jsonify({"success": True})

    with get_db() as db:
        first = db.execute(
            "SELECT * FROM students WHERE id = ?", (first_id,)
        ).fetchone()
        second = db.execute(
            "SELECT * FROM students WHERE id = ?", (second_id,)
        ).fetchone()

        if first is None or second is None:
            return jsonify({"error": "Siswa tidak ditemukan"}), 404

        # Temporary position avoids the UNIQUE seat constraint.
        temp_row = 50000 + first_id
        db.execute(
            "UPDATE students SET seat_row = ? WHERE id = ?",
            (temp_row, first_id)
        )
        db.execute(
            "UPDATE students SET seat_row = ?, seat_col = ? WHERE id = ?",
            (first["seat_row"], first["seat_col"], second_id)
        )
        db.execute(
            "UPDATE students SET seat_row = ?, seat_col = ? WHERE id = ?",
            (second["seat_row"], second["seat_col"], first_id)
        )

    return jsonify({"success": True})


@app.delete("/api/records/<int:record_id>")
def delete_record(record_id):
    with get_db() as db:
        record = db.execute("""
            SELECT r.game, s.name AS student_name
            FROM records r JOIN students s ON s.id = r.student_id
            WHERE r.id = ?
        """, (record_id,)).fetchone()
        if record is None:
            return jsonify({"error": "Catatan tidak ditemukan"}), 404

        db.execute("""
            INSERT INTO audit_log(student_name, action, details)
            VALUES (?, ?, ?)
        """, (
            record["student_name"],
            "Catatan dihapus",
            record["game"]
        ))
        db.execute("DELETE FROM records WHERE id = ?", (record_id,))

    return jsonify({"success": True})


@app.get("/api/export.csv")
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nama siswa", "Tanggal", "Jenis game", "Keterangan"])

    with get_db() as db:
        rows = db.execute("""
            SELECT s.name, r.record_date, r.game, r.note
            FROM records r
            JOIN students s ON s.id = r.student_id
            ORDER BY r.record_date DESC, s.name
        """).fetchall()

        for row in rows:
            writer.writerow([
                row["name"], row["record_date"],
                row["game"], row["note"]
            ])

    content = "\ufeff" + output.getvalue()
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                "attachment; filename=classlog-records.csv"
        }
    )


@app.post("/api/students")
def add_student():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:80]

    if not name:
        return jsonify({"error": "Nama siswa wajib diisi"}), 400

    with get_db() as db:
        cursor = db.execute("""
            SELECT COALESCE(MAX(seat_row), 1) AS r,
                   COALESCE(MAX(seat_col), 0) AS c
            FROM students
        """).fetchone()

        next_row = cursor["r"]
        next_col = cursor["c"] + 1

        if next_col > 4:
            next_row += 1
            next_col = 1

        db.execute("""
            INSERT INTO students(name, seat_row, seat_col)
            VALUES (?, ?, ?)
        """, (name, next_row, next_col))

    return jsonify({"success": True}), 201


@app.get("/api/stats")
def statistics():
    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7

    if days not in (7, 30):
        days = 7

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    start = start_date.isoformat()
    end = end_date.isoformat()

    with get_db() as db:
        trend_rows = db.execute("""
            SELECT record_date, COUNT(*) AS total
            FROM records
            WHERE record_date BETWEEN ? AND ?
            GROUP BY record_date
            ORDER BY record_date
        """, (start, end)).fetchall()

        game_rows = db.execute("""
            SELECT game, COUNT(*) AS total
            FROM records
            WHERE record_date BETWEEN ? AND ?
            GROUP BY game
            ORDER BY total DESC, game ASC
            LIMIT 8
        """, (start, end)).fetchall()

        student_rows = db.execute("""
            SELECT s.name, COUNT(r.id) AS total
            FROM records r
            JOIN students s ON s.id = r.student_id
            WHERE r.record_date BETWEEN ? AND ?
            GROUP BY s.id, s.name
            ORDER BY total DESC, s.name ASC
            LIMIT 10
        """, (start, end)).fetchall()

        total = db.execute("""
            SELECT COUNT(*) FROM records
            WHERE record_date BETWEEN ? AND ?
        """, (start, end)).fetchone()[0]

        affected = db.execute("""
            SELECT COUNT(DISTINCT student_id) FROM records
            WHERE record_date BETWEEN ? AND ?
        """, (start, end)).fetchone()[0]

    trend_map = {r["record_date"]: r["total"] for r in trend_rows}
    labels = []
    values = []

    for offset in range(days):
        current = start_date + timedelta(days=offset)
        labels.append(current.isoformat())
        values.append(trend_map.get(current.isoformat(), 0))

    return jsonify({
        "days": days,
        "start": start,
        "end": end,
        "total": total,
        "affected_students": affected,
        "trend": {"labels": labels, "values": values},
        "games": {
            "labels": [r["game"] for r in game_rows],
            "values": [r["total"] for r in game_rows]
        },
        "students": {
            "labels": [r["name"] for r in student_rows],
            "values": [r["total"] for r in student_rows]
        }
    })


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
