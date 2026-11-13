"""위험도 예측 서비스 (C-2 모델을 API로)

POST /risk/predict  {"raw": {원시 값 13개, 숫자 또는 null}} → {"prob", "reasons": [[group, 기여]], "model"}
- 계산은 기준 구현 ai/risk/model.py를 그대로 쓴다. 서버 PHP(ipp_risk_predict)와 결과가 같아야 한다
- 단계(낮음/보통/높음), 문구, 이유 문장, DB 조회, 기록은 서버 PHP가 한다 (기준값이 한 곳에만 있게)
- 모델 파일이 바뀌면(수정 시각) 다음 요청에서 다시 읽는다. 없거나 형식이 틀리면 503 → PHP가 직접 계산
"""
import os

from fastapi import APIRouter, HTTPException
from pydantic import create_model

from risk import schema as S
from risk.model import RiskModel

from .common import Num, StrictBody

FORMAT = 'risk-logreg/1'

# 원시 값 칸 (ai/risk/schema.py RAW). 빠진 칸은 모름(null)
RiskRaw = create_model('RiskRaw', __base__=StrictBody, **{name: (Num, None) for name in S.RAW_FIELDS})


class PredictRequest(StrictBody):
    raw: RiskRaw


class ModelHolder:
    """모델 JSON을 읽어 두고, 파일 수정 시각이 바뀌면 다시 읽는다"""

    def __init__(self, path):
        self.path = path
        self._stamp = None
        self._model = None

    def get(self):
        try:
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            self._stamp, self._model = None, None
            return None
        if stamp != self._stamp:
            self._stamp, self._model = stamp, self._load()
        return self._model

    def _load(self):
        try:
            m = RiskModel.load(self.path)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        d = m.data
        if d.get('format') != FORMAT or len(m.features) != len(m.coef):
            return None
        if any(f['raw'] not in S.RAW_FIELDS for f in m.features):
            return None   # 이 서버가 받지 않는 원시 값을 쓰는 모델
        return m


def make_router(model_file):
    holder = ModelHolder(model_file)
    router = APIRouter(prefix='/risk', tags=['risk'])

    def need_model():
        m = holder.get()
        if m is None:
            raise HTTPException(503, 'risk model unavailable')
        return m

    @router.post('/predict')
    def predict(req: PredictRequest):
        m = need_model()
        prob, reasons, _ = m.predict(req.raw.model_dump())
        return {'prob': prob, 'reasons': [[g, c] for g, c in reasons], 'model': str(m.data['version'])}

    def health():
        m = holder.get()
        return {'model': str(m.data['version']), 'format': FORMAT} if m else None

    return router, health
