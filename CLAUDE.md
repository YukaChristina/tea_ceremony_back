# 茶道稽古記録アプリ — Backend

## 技術スタック
- Python / FastAPI
- SQLAlchemy + Supabase PostgreSQL
- Supabase Auth (JWT検証: EdDSA/RS256/HS256 自動判別)
- Cloudinary（写真アップロード）

## ファイル構成
- `main.py` — APIエンドポイント全て
- `db.py` — DB接続設定
- `requirements.txt` — 依存パッケージ

## 環境変数（Render）
- `DATABASE_URL` — Supabase Connection Pooler URL（IPv4対応）
- `SUPABASE_JWT_SECRET` — Supabase JWT Secret
- `SUPABASE_URL` — https://xxx.supabase.co

## APIエンドポイント
- `POST /lessons` — 稽古作成
- `GET /lessons` — 稽古一覧
- `GET /lessons/{id}` — 稽古詳細（茶室/亭主/客タブ構造）
- `PATCH /lessons/{id}` — 稽古更新
- `DELETE /lessons/{id}/items` — 道具一括削除
- `DELETE /lessons/{id}/role-entries` — 点前エントリ一括削除
- `POST /lessons/{id}/role-entries` — 点前エントリ追加
- `POST /lessons/{id}/items` — 道具追加
- `POST /lessons/{id}/photos` — 写真URL保存
- `GET /lessons/{id}/photos` — 稽古の写真一覧
- `GET /photos` — 全写真一覧（アルバム用）
- `GET /search` — キーワード・条件検索

## 認証
全エンドポイントで `Depends(get_current_user_id)` が必要。
初回ログイン時に `users` テーブルへ自動登録。

## DBテーブル
- `users` — supabase_uid, email, display_name, role
- `lessons` — user_id, practiced_on, practice_name
- `role_entries` — lesson_id, role(teishu/kyaku), temae_name, note
- `lesson_items` — lesson_id, role_entry_id, section, item_type, title, mei, maker, note
- `lesson_photos` — lesson_id, user_id, url

## デプロイ
Render (Web Service) — `uvicorn main:app --host 0.0.0.0 --port $PORT`