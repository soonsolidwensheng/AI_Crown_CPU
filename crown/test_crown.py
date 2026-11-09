#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import index


DEFAULT_INPUT = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "crown-input"
    / "AABA-252S.innerShell.json"
)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "out"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeRequests:
    def __init__(self, payload):
        self.payload = payload
        self.get_calls = []
        self.put_calls = []

    def get(self, url):
        self.get_calls.append(url)
        return FakeResponse(self.payload)

    def put(self, url, json, headers):
        self.put_calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
            }
        )
        return FakeResponse({})


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"result saved: {path}")


def validate_result(data):
    assert isinstance(data, dict)
    assert "crown" in data

    crown_data = data["crown"]
    assert "state" in crown_data

    state = crown_data["state"]
    assert isinstance(state["errorCode"], int)
    assert isinstance(state["errorMsg"], str)

    return crown_data


def test_direct_json(input_path, output_dir):
    input_data = load_json(input_path)

    response = index.handler(input_data, None)
    crown_data = validate_result(response)

    write_json(
        output_dir / f"{Path(input_path).stem}.direct.result.json",
        response,
    )

    state = crown_data["state"]
    assert state["errorCode"] == 200

    result = crown_data["result"]
    summary = result["summary"]

    assert summary["toothCount"] > 0
    assert (
        summary["successCount"] + summary["failureCount"]
        == summary["toothCount"]
    )

    print("direct JSON test: passed")
    print(json.dumps(state, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))


def test_url_json(input_path, output_dir):
    input_data = load_json(input_path)

    fake_requests = FakeRequests(input_data)
    original_requests = index.requests
    index.requests = fake_requests

    try:
        response = index.handler(
            {
                "source_url": "https://example.invalid/input.json",
                "target_url": "https://example.invalid/output.json",
                "job_id": "test-crown-job",
            },
            None,
        )
    finally:
        index.requests = original_requests

    crown_data = validate_result(response)
    state = crown_data["state"]

    assert state["status"] == "success"
    assert state["errorCode"] == 200
    assert state["job_id"] == "test-crown-job"

    assert len(fake_requests.put_calls) == 1

    upload = fake_requests.put_calls[0]
    assert upload["headers"] == {"Content-Type": "application/json"}

    uploaded_result = upload["json"]
    validate_result(uploaded_result)

    write_json(
        output_dir / f"{Path(input_path).stem}.url.result.json",
        uploaded_result,
    )

    print("URL JSON test: passed")
    print(json.dumps(state, ensure_ascii=False))


def test_custom_event_real(output_dir):
    """
    使用真实的 S3 预签名 URL 进行测试（不模拟网络请求）。
    """
    event = {
        "job_id": "test crown thickness",
        "target_url": (
            "https://sprint-ray-files-dev.s3.amazonaws.com/ai-crown/"
            "01a021bf-12a7-799c-bc26-2473b31409bf/"
            "a55b5487-a05a-4526-bc5d-6861c6b7ee4c/input/"
            "crown_thickness_output.json"
            "?AWSAccessKeyId=AKIA2UWYY6B7PJKZDWHC"
            "&Content-Type=binary%2Foctet-stream"
            "&Expires=1787361927"
            "&Signature=u%2Fl5ajhDvOeoY6BecLbLiLiF0to%3D"
        ),
        "source_url": (
            "https://sprint-ray-files-dev.s3.amazonaws.com/ai-crown/"
            "01a021bf-12a7-799c-bc26-2473b31409bf/"
            "a55b5487-a05a-4526-bc5d-6861c6b7ee4c/input/"
            "crown_thickness.json"
            "?AWSAccessKeyId=AKIA2UWYY6B7PJKZDWHC"
            "&Expires=1787361927"
            "&Signature=FKHdKNvpAlq3bWL07cumaWM2cPw%3D"
        ),
    }

    if index.requests is None:
        raise RuntimeError("requests package is not installed or not imported.")

    response = index.handler(event, None)
    crown_data = validate_result(response)
    state = crown_data["state"]

    # 先打印状态，方便查看错误详情
    print(f"State: {json.dumps(state, ensure_ascii=False)}")

    # 如果状态不是 success，抛出带详细信息的异常
    if state["status"] != "success":
        raise AssertionError(
            f"Real test failed: status={state['status']}, "
            f"errorCode={state['errorCode']}, "
            f"errorMsg={state['errorMsg']}"
        )

    assert state["errorCode"] == 200
    assert state["job_id"] == "test crown thickness"

    result = crown_data.get("result")
    assert result is not None, "Result should not be None"

    write_json(
        output_dir / "custom_event_real.response.json",
        response,
    )

    write_json(
        output_dir / "custom_event_real.processed.json",
        result,
    )

    print("custom event real test: passed")
    if "summary" in result:
        print(json.dumps(result["summary"], ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Crown JSON input file (used for mock tests).",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory used to save generated JSON results.",
    )

    parser.add_argument(
        "--real",
        action="store_true",
        help="Run the real network test (requires valid S3 URLs).",
    )

    args = parser.parse_args()

    test_direct_json(args.input, args.output_dir)
    test_url_json(args.input, args.output_dir)

    if args.real:
        test_custom_event_real(args.output_dir)

    print("all crown tests: passed")


if __name__ == "__main__":
    main()