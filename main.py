from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from db import SessionLocal
from pydantic import BaseModel
from datetime import date

app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tea-ceremony-front.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health/db")
def health_db():
    """
    DB疎通確認API:
    - SELECT 1 が成功するか
    - users/lessons/lesson_items が存在するか（SHOW TABLES）
    """
    db = SessionLocal()
    try:
        # 1) 疎通確認
        one = db.execute(text("SELECT 1")).scalar()

        # 2) テーブル一覧確認（任意だが分かりやすい）
        tables = db.execute(text("SHOW TABLES")).fetchall()
        table_names = [row[0] for row in tables]

        return {
            "db_ok": True,
            "select_1": one,
            "tables": table_names
        }
    finally:
        db.close()

@app.get("/debug/db")
def debug_db():
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT DATABASE() AS current_db, @@hostname AS host, @@port AS port")).mappings().first()
        return dict(row)
    finally:
        db.close()
        
class LessonCreate(BaseModel):
    practiced_on: date
    practice_name: str | None = None


@app.post("/lessons")
def create_lesson(payload: LessonCreate):
    """
    稽古を1件作成するAPI
    - user_id は MVPでは固定で 1
    """
    db = SessionLocal()
    try:
        sql = text("""
            INSERT INTO lessons (user_id, practiced_on, practice_name)
            VALUES (:user_id, :practiced_on, :practice_name)
        """)
        result = db.execute(
            sql,
            {
                "user_id": 1,
                "practiced_on": payload.practiced_on,
                "practice_name": payload.practice_name,
            }
        )
        db.commit()

        lesson_id = result.lastrowid
        return {
            "lesson_id": lesson_id,
            "practiced_on": payload.practiced_on,
            "practice_name": payload.practice_name
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

from typing import Optional, Literal
from fastapi import Query

# 稽古一覧取得API（亭主/客の最初の点前名も含む）
from fastapi import HTTPException

@app.get("/lessons")
def list_lessons():
    db = SessionLocal()
    try:
        sql = text("""
            SELECT
              l.id,
              l.practiced_on,
              l.practice_name,

              (
                SELECT re.temae_name
                FROM role_entries re
                WHERE re.lesson_id = l.id
                  AND re.role = 'teishu'
                  AND re.temae_name IS NOT NULL
                ORDER BY re.id DESC
                LIMIT 1
              ) AS teishu_temae_name,

              (
                SELECT re.temae_name
                FROM role_entries re
                WHERE re.lesson_id = l.id
                  AND re.role = 'kyaku'
                  AND re.temae_name IS NOT NULL
                ORDER BY re.id DESC
                LIMIT 1
              ) AS kyaku_temae_name

            FROM lessons l
            WHERE l.user_id = 1
            ORDER BY l.practiced_on DESC, l.id DESC
            LIMIT 200
        """)
        rows = db.execute(sql).mappings().all()

        return [
            {
                "id": r["id"],
                "practiced_on": str(r["practiced_on"]),
                "practice_name": r["practice_name"],
                "teishu_temae_name": r["teishu_temae_name"],
                "kyaku_temae_name": r["kyaku_temae_name"],
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/search")
#検索条件を全部"任意"として受け取るための入口（Optional, なければNone）
def search_items(
    query: Optional[str] = Query(default=None, description="検索窓キーワード（銘/作者/メモなどを横断）"),
    year: Optional[int] = Query(default=None, description="年（例: 2026）"),
    practice_name: Optional[str] = Query(default=None, description="稽古名（部分一致）"),
    item_type: Optional[str] = Query(default=None, description="道具軸（例: chawan）"),
    section: Optional[str] = Query(default=None, description="chashitsu / teishu / kyaku"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    振り返り検索（1本で両対応）
    - ①事前フィルタ: year / practice_name / item_type / section
    - ②検索窓: query（search_text LIKE）
    - 使わない条件はNULL扱い → WHEREで無視される
    """
    db = SessionLocal()
    try:
        # queryが空文字やスペースだけの場合もNone扱いに寄せる→検索する場合だけ%xxx%を作る）
        q = (query or "").strip()
        q_like = f"%{q}%" if q else None

        #稽古と道具を１セットとして取得し、NULL以外の内容で絞り込み、並び替え、ページング
        sql = text("""
            SELECT
              l.id            AS lesson_id,
              l.practiced_on  AS practiced_on,
              l.practice_name AS practice_name,
              i.id            AS item_id,
              i.section       AS section,
              i.item_type     AS item_type,
              i.title         AS title,
              i.mei           AS mei,
              i.maker         AS maker,
              i.note          AS note
            FROM lessons l
            JOIN lesson_items i ON i.lesson_id = l.id
            WHERE l.user_id = :user_id
              AND (:year IS NULL OR YEAR(l.practiced_on) = :year)
              AND (:practice_name IS NULL OR l.practice_name LIKE CONCAT('%', :practice_name, '%'))
              AND (:item_type IS NULL OR i.item_type = :item_type)
              AND (:section IS NULL OR i.section = :section)
              AND (:q_like IS NULL OR i.search_text LIKE :q_like)
            ORDER BY l.practiced_on DESC, i.id DESC
            LIMIT :limit OFFSET :offset
        """)
        #SQL結果を辞書形式で受け取るためにmappings()を使用（Pythonで扱いやすくなる）
        rows = db.execute(
            sql,
            {
                "user_id": 1,
                "year": year,
                "practice_name": practice_name,
                "item_type": item_type,
                "section": section,
                "q_like": q_like,
                "limit": limit,
                "offset": offset,
            },
        ).mappings().all()

        # フロントがそのまま使えるJSONにするために整形
        results = []
        for r in rows:
            results.append({
                "lesson_id": r["lesson_id"],
                "practiced_on": str(r["practiced_on"]),
                "practice_name": r["practice_name"],
                "item": {
                    "item_id": r["item_id"],
                    "section": r["section"],
                    "item_type": r["item_type"],
                    "title": r["title"],
                    "mei": r["mei"],
                    "maker": r["maker"],
                    "note": r["note"],
                }
            })

        #検索結果＋検索条件を見せる（なぜ？→フロントで状態管理しやすくするため）
        return {
            "count": len(results),
            "limit": limit,
            "offset": offset,
            "filters": {
                "query": query,
                "year": year,
                "practice_name": practice_name,
                "item_type": item_type,
                "section": section,
            },
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

#稽古1件を開いたときに茶室/亭主/客のタブ構造で返すAPI
@app.get("/lessons/{lesson_id}")
def get_lesson_detail(lesson_id: int):
    """
    1つの稽古（lesson）を、タブ表示しやすい構造で返す
    - chashitsu: role_entry_id = NULL の道具
    - teishu/kyaku: role_entries の entry ごとに items をまとめる
    """
    db = SessionLocal()
    try:
        # 0) lesson本体を取得（いまは user_id=1 固定）
        lesson_sql = text("""
            SELECT id, practiced_on, practice_name
            FROM lessons
            WHERE id = :lesson_id AND user_id = :user_id
            LIMIT 1
        """)
        lesson = db.execute(
            lesson_sql, {"lesson_id": lesson_id, "user_id": 1}
        ).mappings().first()

        if not lesson:
            raise HTTPException(status_code=404, detail="Lesson not found")

        # 1) role_entries を取得（亭主/客の点前単位）
        entries_sql = text("""
            SELECT id, lesson_id, role, temae_name, note, created_at
            FROM role_entries
            WHERE lesson_id = :lesson_id
            ORDER BY id ASC
        """)
        entries = db.execute(entries_sql, {"lesson_id": lesson_id}).mappings().all()

        # entry_id -> entry情報（itemsは後で詰める）
        entry_map = {}
        for e in entries:
            entry_map[e["id"]] = {
                "role_entry_id": e["id"],
                "role": e["role"],
                "temae_name": e["temae_name"],
                "note": e["note"],
                "created_at": str(e["created_at"]),
                "items": [],
            }

        # 2) items（道具）を全部取得
        items_sql = text("""
            SELECT
              id,
              lesson_id,
              role_entry_id,
              section,
              item_type,
              title,
              mei,
              maker,
              note,
              created_at
            FROM lesson_items
            WHERE lesson_id = :lesson_id
            ORDER BY id ASC
        """)
        items = db.execute(items_sql, {"lesson_id": lesson_id}).mappings().all()

        # 3) タブ構造にグルーピング
        # - 茶室: role_entry_id が NULL のもの
        chashitsu_items = []

        # - 亭主/客: entryごとに item を突っ込む
        for it in items:
            item_payload = {
                "item_id": it["id"],
                "role_entry_id": it["role_entry_id"],
                "section": it["section"],  # 移行期間の名残として残しておく（将来消してもOK）
                "item_type": it["item_type"],
                "title": it["title"],
                "mei": it["mei"],
                "maker": it["maker"],
                "note": it["note"],
                "created_at": str(it["created_at"]),
            }

            if it["role_entry_id"] is None:
                chashitsu_items.append(item_payload)
            else:
                # role_entry_id があるのに entry_map にない場合（データ不整合）もあり得るので防御
                entry = entry_map.get(it["role_entry_id"])
                if entry is None:
                    # ここでは落とさず、茶室側に逃がす or unknown に入れるなどが選べる
                    # MVPでは "unknown_entries" にまとめるのが安全
                    # ただし、今回は chashitsu_items に逃がして見失わないようにする
                    chashitsu_items.append(item_payload)
                else:
                    entry["items"].append(item_payload)

        # 4) roleごとに entries を分ける（タブ固定：茶室 / 亭主 / 客）
        teishu_entries = [v for v in entry_map.values() if v["role"] == "teishu"]
        kyaku_entries = [v for v in entry_map.values() if v["role"] == "kyaku"]

        # 5) レスポンス
        return {
            "lesson": {
                "id": lesson["id"],
                "practiced_on": str(lesson["practiced_on"]),
                "practice_name": lesson["practice_name"],  # 稽古名（イベント名）
            },
            "tabs": {
                "chashitsu": {
                    "items": chashitsu_items
                },
                "teishu": {
                    "entries": teishu_entries
                },
                "kyaku": {
                    "entries": kyaku_entries
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# 亭主/客の点前エントリを追加するAPI
class RoleEntryCreate(BaseModel):
    role: Literal["teishu", "kyaku"]
    temae_name: Optional[str] = None
    note: Optional[str] = None

@app.post("/lessons/{lesson_id}/role-entries")
def create_role_entry(lesson_id: int, body: RoleEntryCreate):
    db = SessionLocal()
    try:
        # lesson存在確認（いまは user_id=1 固定）
        lesson = db.execute(
            text("SELECT id FROM lessons WHERE id=:lesson_id AND user_id=:user_id LIMIT 1"),
            {"lesson_id": lesson_id, "user_id": 1},
        ).mappings().first()
        if not lesson:
            raise HTTPException(status_code=404, detail="Lesson not found")

        # role_entry 追加
        db.execute(
            text("""
                INSERT INTO role_entries (lesson_id, role, temae_name, note)
                VALUES (:lesson_id, :role, :temae_name, :note)
            """),
            {
                "lesson_id": lesson_id,
                "role": body.role,
                "temae_name": body.temae_name,
                "note": body.note,
            },
        )
        db.commit()

        # 追加したidを返す（MySQLで安全に取る簡易版）
        new_row = db.execute(
            text("""
                SELECT id, lesson_id, role, temae_name, note, created_at
                FROM role_entries
                WHERE lesson_id=:lesson_id AND role=:role
                ORDER BY id DESC
                LIMIT 1
            """),
            {"lesson_id": lesson_id, "role": body.role},
        ).mappings().first()

        return {"role_entry": new_row}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# 道具追加API（role_entry_id対応版）
class ItemCreate(BaseModel):
    role_entry_id: Optional[int] = None  # 亭主/客点前に紐づける。茶室ならNone
    section: Optional[Literal["chashitsu", "teishu", "kyaku"]] = None  # 互換用（任意）
    item_type: str
    title: Optional[str] = None
    mei: Optional[str] = None
    maker: Optional[str] = None
    note: Optional[str] = None

from pydantic import BaseModel
from typing import Optional, Literal
from fastapi import HTTPException
from sqlalchemy import text

# 追加用Pydanticモデル
class ItemCreate(BaseModel):
    role_entry_id: Optional[int] = None  # 亭主/客点前に紐づける。茶室ならNone
    section: Optional[Literal["chashitsu", "teishu", "kyaku"]] = None  # 互換用（任意）
    item_type: str
    title: Optional[str] = None
    mei: Optional[str] = None
    maker: Optional[str] = None
    note: Optional[str] = None


@app.post("/lessons/{lesson_id}/items")
def add_item_to_lesson(lesson_id: int, body: ItemCreate):
    """
    道具追加API（role_entry_id対応 + search_text自動生成）

    ルール：
    - role_entry_id がある → その role_entries がこの lesson のものか検証し、role から section を自動推定
    - role_entry_id がない → 茶室（chashitsu）扱い（ただし互換で section 指定があれば尊重）
    - search_text は、後から検索しやすいように自動生成して保存
    """
    db = SessionLocal()
    try:
        USER_ID = 1  # MVPは固定（後で認証を入れたら差し替え）

        # 0) lesson存在確認 + 稽古名取得（search_text用）
        lesson_row = db.execute(
            text("""
                SELECT id, practice_name
                FROM lessons
                WHERE id = :lesson_id AND user_id = :user_id
                LIMIT 1
            """),
            {"lesson_id": lesson_id, "user_id": USER_ID},
        ).mappings().first()

        if not lesson_row:
            raise HTTPException(status_code=404, detail="Lesson not found")

        practice_name = lesson_row["practice_name"] or ""

        # 1) section の決定（role_entry_id優先）
        inferred_section = None

        if body.role_entry_id is not None:
            # role_entry がこのlessonに属するか検証
            entry = db.execute(
                text("""
                    SELECT id, role, temae_name
                    FROM role_entries
                    WHERE id = :role_entry_id AND lesson_id = :lesson_id
                    LIMIT 1
                """),
                {"role_entry_id": body.role_entry_id, "lesson_id": lesson_id},
            ).mappings().first()

            if not entry:
                raise HTTPException(status_code=400, detail="Invalid role_entry_id for this lesson")

            # roleからsectionを自動推定
            if entry["role"] == "teishu":
                inferred_section = "teishu"
            elif entry["role"] == "kyaku":
                inferred_section = "kyaku"
            else:
                # 将来 role が増えた場合の保険
                inferred_section = body.section or "chashitsu"

            temae_name = entry["temae_name"] or ""
        else:
            # role_entry_idがない → 茶室（互換でsection指定があれば使う）
            inferred_section = body.section or "chashitsu"
            temae_name = ""

        # 2) search_text を生成（検索用）
        # ※ここは後で好きなだけ増やせます（作者/銘/稽古名/点前名など）
        parts = [
            inferred_section,
            temae_name,            # 点前名（role_entryがある場合）
            body.item_type,
            body.title or "",
            body.mei or "",
            body.maker or "",
            body.note or "",
            practice_name,         # 稽古名（イベント名）
        ]
        search_text = " ".join([p for p in parts if p])

        # 3) INSERT
        db.execute(
            text("""
                INSERT INTO lesson_items
                  (lesson_id, role_entry_id, section, item_type, title, mei, maker, note, search_text)
                VALUES
                  (:lesson_id, :role_entry_id, :section, :item_type, :title, :mei, :maker, :note, :search_text)
            """),
            {
                "lesson_id": lesson_id,
                "role_entry_id": body.role_entry_id,
                "section": inferred_section,
                "item_type": body.item_type,
                "title": body.title,
                "mei": body.mei,
                "maker": body.maker,
                "note": body.note,
                "search_text": search_text,
            },
        )
        db.commit()

        # 4) 追加した行を返す（簡易：直近1件）
        new_item = db.execute(
            text("""
                SELECT
                  id, lesson_id, role_entry_id, section, item_type, title, mei, maker, note, search_text, created_at
                FROM lesson_items
                WHERE lesson_id = :lesson_id
                ORDER BY id DESC
                LIMIT 1
            """),
            {"lesson_id": lesson_id},
        ).mappings().first()

        return {"item": new_item}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
