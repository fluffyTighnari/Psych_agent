"""测量 cross-encoder 吞吐，估算全量打分矩阵耗时。"""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.helper.reranker import Reranker  # noqa
from config.model_config import RERANKING_MODEL  # noqa

t0 = time.time()
r = Reranker(RERANKING_MODEL)
print("load %.1fs" % (time.time() - t0))

texts = ["这是一段关于焦虑与自我和解的测试文本" * 5] * 32
pairs = [("我最近总是内耗，怎么和自己和解", t) for t in texts]
t0 = time.time()
s = r.model.predict(pairs)
dt = time.time() - t0
print("32 pairs %.2fs -> %.1f pairs/s" % (dt, 32 / dt))
print("score range", float(min(s)), float(max(s)))
t0 = time.time()
s2 = r.model.predict(pairs)
print("warm 32 pairs %.2fs -> %.1f pairs/s" % (time.time() - t0, 32 / (time.time() - t0)))
