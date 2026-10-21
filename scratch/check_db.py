import os
from sqlalchemy import select, create_engine
from db.orm import Base, TranscriptRow, TranscriptVersionRow
from db.session import build_session_factory, session_scope

# Ensure env variables are loaded (e.g. database URL)
from dotenv import load_dotenv
load_dotenv(".env")

db_url = os.environ.get("CREATIVE_AGENT_DATABASE_URL")
print(f"Connecting to database: {db_url.split('@')[-1]}")

engine = create_engine(db_url)
factory = build_session_factory()

with session_scope(factory) as session:
    stmt = select(TranscriptRow).order_by(TranscriptRow.updated_at.desc()).limit(10)
    transcripts = session.scalars(stmt).all()
    
    if not transcripts:
        print("No transcripts found in the database.")
    else:
        print("\n--- Latest Transcripts ---")
        for tx in transcripts:
            print(f"ID: {tx.id} | Status: {tx.status} | Created At: {tx.created_at} | Updated At: {tx.updated_at}")
            # Get versions
            v_stmt = select(TranscriptVersionRow).where(TranscriptVersionRow.transcript_id == tx.id).order_by(TranscriptVersionRow.created_at.asc())
            versions = session.scalars(v_stmt).all()
            for v in versions:
                print(f"  -> Version ID: {v.id} | Kind: {v.version_kind} | Created By: {v.created_by_agent} | Created At: {v.created_at}")
