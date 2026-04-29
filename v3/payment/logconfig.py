"""ログ formatter. 1 line = 1 JSON object で stdout に出す.

Datadog / CloudWatch 等の log collector が parse なしで取り込める形式にすることが目的.
request 単位の trace ID は上流 LB / API gateway 側に任せる (本 app では持たない).
"""

import json
import logging
from datetime import UTC, datetime

# JsonFormatter で「LogRecord 標準属性」と判定して payload から除外するキー.
# logging.LogRecord の __dict__ は呼び出しごとに同じキー集合を持つので
# ダミー record から 1 度だけ抽出する. message / asctime は format 後に追加されるため別途 union.
_STD_RECORD_KEYS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None,
    ).__dict__.keys(),
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """1 line = 1 JSON object の formatter.

    `logger.info("msg", extra={"order_id": "x"})` で渡された extra は top-level に
    フィールドとして展開される (将来構造化したくなった時の拡張ポイント).
    今のところ呼び出し側は素朴な %s 形式 + message 内に埋め込む方針.
    """

    def format(self, record: logging.LogRecord) -> str:
        # 1. 必須フィールド (timestamp は UTC ISO8601)
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 2. 例外情報 (logger.exception / exc_info=True で添付される)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        # 3. extra={...} で渡された任意フィールド (record の標準属性以外を全部拾う).
        for key, value in record.__dict__.items():
            if key not in _STD_RECORD_KEYS:
                payload[key] = value

        # default=str で datetime / Decimal / Exception 等を文字列化 (json.dumps の保険).
        # ensure_ascii=False で日本語をそのまま出す (escape されない方が grep しやすい).
        return json.dumps(payload, default=str, ensure_ascii=False)
