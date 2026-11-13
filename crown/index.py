import json
import traceback
import uuid
from urllib.parse import urlparse, parse_qs

import crown

try:
    import requests
except ImportError:
    requests = None


def _status_response(status, error_code, error_message, job_id):
    return {
        "crown": {
            "state": {
                "status": status,
                "errorCode": error_code,
                "errorMsg": error_message,
                "job_id": job_id,
            }
        }
    }


def _error_response(error_message):
    return {
        "crown": {
            "result": None,
            "state": {
                "status": "failed",
                "errorCode": 215,
                "errorMsg": error_message,
            },
        }
    }


def _process_url_event(event):
    job_id = event.get("job_id") or str(uuid.uuid4())
    source_url = event["source_url"]
    target_url = event["target_url"]

    if requests is None:
        return _status_response(
            "failed",
            211,
            "The requests package is required.",
            job_id,
        )

    try:
        response = requests.get(source_url)
        response.raise_for_status()
        input_json = json.dumps(response.json())
    except Exception as exception:
        error_message = f"Failed to read from source_url: {exception}"
        print(error_message)
        return _status_response(
            "failed",
            211,
            error_message,
            job_id,
        )

    try:
        output_json = crown.process_crown_json(input_json)
    except Exception as exception:
        error_message = (
            f"Processing failed: {exception}\n"
            f"{traceback.format_exc()}"
        )
        print(error_message)
        return _status_response(
            "failed",
            212,
            error_message,
            job_id,
        )

    try:
        result = json.loads(output_json)
    except Exception as exception:
        error_message = (
            f"Failed to parse processing result as JSON: {exception}"
        )
        print(error_message)
        return _status_response(
            "failed",
            214,
            error_message,
            job_id,
        )

    # -------------------- 修改开始 --------------------
    # 从 target_url 中提取 Content-Type 参数，若无则默认为 binary/octet-stream
    parsed_url = urlparse(target_url)
    query_params = parse_qs(parsed_url.query)
    content_type = query_params.get('Content-Type', ['binary/octet-stream'])[0]
    # -------------------- 修改结束 --------------------

    try:
        response = requests.put(
            target_url,
            json=result,
            headers={"Content-Type": content_type},   # 使用动态提取的 content_type
        )
        response.raise_for_status()
    except Exception as exception:
        error_message = f"Failed to write to target_url: {exception}"
        print(error_message)
        return _status_response(
            "failed",
            213,
            error_message,
            job_id,
        )

    result_state = result.get("crown", {}).get("state", {})
    error_code = result_state.get("errorCode", 500)
    error_message = result_state.get("errorMsg", "Unknown error")
    status = "success" if error_code == 200 else "failed"

    return _status_response(
        status,
        error_code,
        error_message,
        job_id,
    )


def handler(event, context):
    try:
        if not isinstance(event, dict):
            return _error_response("event must be a JSON object.")

        has_source_url = bool(event.get("source_url"))
        has_target_url = bool(event.get("target_url"))

        # 两个 URL 同时存在时进入 URL 模式
        if has_source_url and has_target_url:
            return _process_url_event(event)

        # URL 不完整，但存在 crownInput 时直接处理
        if "crownInput" in event:
            output_json = crown.process_crown_json(
                json.dumps(event)
            )
            return json.loads(output_json)

        return _error_response(
            "source_url and target_url must be provided together, "
            "or crownInput must be provided."
        )

    except Exception as exception:
        return _error_response(str(exception))
