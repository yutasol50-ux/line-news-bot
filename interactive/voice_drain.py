"""起動時/定期に、未完了(pending/に残った)音声を再処理する。"""
import os
from interactive import voice_intake

def drain(*, process=voice_intake.process):
    d = voice_intake.PENDING_DIR
    if not os.path.isdir(d): return 0
    mids = sorted({name.rsplit(".",1)[0] for name in os.listdir(d)})
    for mid in mids:
        try:
            process(mid)
        except Exception as e:
            print(f"[ERROR] voice_drain {mid}: {e}")
    return len(mids)

if __name__ == "__main__":
    print(f"drained {drain()}")
