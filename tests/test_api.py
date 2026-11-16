"""端到端 API 测试：会话、分析、选择、确认、下载、并发失效。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def create(client, original, revised, labels):
    r = client.post("/api/sessions", json={
        "original": original, "revised": revised, "labels": labels})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- 输入校验 ----------------

class TestValidation:
    def test_text_too_long(self, client):
        r = client.post("/api/sessions", json={
            "original": "x" * 121, "revised": "", "labels": []})
        assert r.status_code == 400
        assert "120" in r.json()["detail"]

    def test_text_length_counts_codepoints_not_utf16(self, client):
        # 60 个 emoji = 60 码点（UTF-16 下是 120 个码元），应当接受
        r = client.post("/api/sessions", json={
            "original": "😀" * 60, "revised": "😀" * 60, "labels": []})
        assert r.status_code == 201

    def test_too_many_labels(self, client):
        labels = [{"start": i, "end": i + 1} for i in range(11)]
        r = client.post("/api/sessions", json={
            "original": "abcdefghijk", "revised": "abcdefghijk", "labels": labels})
        assert r.status_code == 400
        assert "10" in r.json()["detail"]

    def test_empty_label_rejected(self, client):
        r = client.post("/api/sessions", json={
            "original": "abc", "revised": "abc",
            "labels": [{"start": 1, "end": 1}]})
        assert r.status_code == 400

    def test_out_of_range_label_rejected(self, client):
        r = client.post("/api/sessions", json={
            "original": "abc", "revised": "abc",
            "labels": [{"start": 0, "end": 4}]})
        assert r.status_code == 400

    def test_overlapping_labels_rejected(self, client):
        r = client.post("/api/sessions", json={
            "original": "abcd", "revised": "abcd",
            "labels": [{"start": 0, "end": 2}, {"start": 1, "end": 3}]})
        assert r.status_code == 400
        assert "重叠" in r.json()["detail"]

    def test_adjacent_labels_allowed(self, client):
        st = create(client, "abcd", "abcd",
                    [{"start": 0, "end": 2}, {"start": 2, "end": 4}])
        assert len(st["labels"]) == 2

    def test_duplicate_id_rejected(self, client):
        r = client.post("/api/sessions", json={
            "original": "abcd", "revised": "abcd",
            "labels": [{"id": "x", "start": 0, "end": 1},
                       {"id": "x", "start": 2, "end": 3}]})
        assert r.status_code == 400

    def test_ids_auto_assigned(self, client):
        st = create(client, "abcd", "abcd", [{"start": 0, "end": 1}])
        assert st["labels"][0]["id"] == "L1"


# ---------------- 分析 ----------------

class TestAnalysis:
    def test_auto(self, client):
        st = create(client, "语料工程师修订OCR文本", "语料工程师修订OCR文本内容",
                    [{"id": "role", "start": 0, "end": 5}])
        lab = st["analysis"]["labels"][0]
        assert lab["status"] == "auto" and lab["possible"] == [0]
        assert st["analysis"]["distance"] == 2

    def test_choice(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        lab = st["analysis"]["labels"] if "labels" in st["analysis"] else None
        lab = st["analysis"]["labels"][0]
        assert lab["status"] == "choice" and lab["possible"] == [0, 3]

    def test_impossible(self, client):
        st = create(client, "中国人民银行", "中国人民银号",
                    [{"id": "bank", "start": 4, "end": 6}])
        lab = st["analysis"]["labels"][0]
        assert lab["status"] == "impossible" and lab["possible"] == []


# ---------------- 确认与下载 ----------------

class TestConfirm:
    def test_auto_confirm_and_download(self, client):
        st = create(client, "语料工程师修订OOCR文本", "语料工程师修订OCR文本",
                    [{"id": "role", "start": 0, "end": 5}])
        sid, rev = st["session_id"], st["revision"]
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] and body["result"]["labels"] == [
            {"id": "role", "start": 0, "end": 5, "text": "语料工程师"}]
        assert body["result"]["revised"] == "语料工程师修订OCR文本"

        d = client.get(f"/api/sessions/{sid}/download")
        assert d.status_code == 200
        assert "attachment" in d.headers["content-disposition"]
        assert d.json()["labels"][0]["id"] == "role"

    def test_choice_requires_selection(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 422
        assert r.json()["detail"]["labels"] == ["rep"]
        # 未确认成功：无结果可下载
        assert client.get(f"/api/sessions/{sid}/download").status_code == 404

    def test_choice_select_then_confirm(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        r = client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev, "selections": {"rep": {"choice": "position", "position": 3}}})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200, r.text
        assert r.json()["result"]["labels"] == [
            {"id": "rep", "start": 3, "end": 6, "text": "abc"}]

    def test_choice_discard(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev, "selections": {"rep": {"choice": "discard"}}})
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200
        assert r.json()["result"]["labels"] == []
        assert r.json()["result"]["meta"]["discarded"] == ["rep"]

    def test_invalid_position_rejected(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        r = client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev, "selections": {"rep": {"choice": "position", "position": 1}}})
        assert r.status_code == 400

    def test_impossible_auto_discarded(self, client):
        st = create(client, "中国人民银行", "中国人民银号",
                    [{"id": "bank", "start": 4, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200
        assert r.json()["result"]["labels"] == []
        assert r.json()["result"]["meta"]["discarded"] == ["bank"]

    def test_conflict_rejected_and_no_partial_result(self, client):
        # abab -> ab：两个标签各自唯一落点都是 [0,2)，联合不可能
        st = create(client, "abab", "ab",
                    [{"id": "x", "start": 0, "end": 2},
                     {"id": "y", "start": 2, "end": 4}])
        sid, rev = st["session_id"], st["revision"]
        # 二者都不是 auto（并非所有最优对齐都保留），需显式选择落点
        assert {l["id"]: l["status"] for l in st["analysis"]["labels"]} == \
            {"x": "choice", "y": "choice"}
        r = client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev,
            "selections": {"x": {"choice": "position", "position": 0},
                           "y": {"choice": "position", "position": 0}}})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["code"] == "conflict"
        assert set(detail["conflicting_labels"]) == {"x", "y"}
        # 失败不留半份结果
        assert client.get(f"/api/sessions/{sid}/download").status_code == 404
        # 丢弃其中一个后成功（selections 为整表替换，需带上 x 的选择）
        client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev,
            "selections": {"x": {"choice": "position", "position": 0},
                           "y": {"choice": "discard"}}})
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200
        assert [l["id"] for l in r.json()["result"]["labels"]] == ["x"]

    def test_confirm_idempotent(self, client):
        st = create(client, "abc", "abc", [{"id": "a", "start": 0, "end": 1}])
        sid, rev = st["session_id"], st["revision"]
        r1 = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        r2 = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r1.status_code == r2.status_code == 200
        assert r2.json()["already"] is True


# ---------------- 并发失效 ----------------

class TestStaleness:
    def test_old_confirm_rejected_after_input_change(self, client):
        st = create(client, "abcabcabc", "abcabc",
                    [{"id": "rep", "start": 3, "end": 6}])
        sid, rev = st["session_id"], st["revision"]
        client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev, "selections": {"rep": {"choice": "position", "position": 3}}})
        # 另一窗口修改了输入
        r = client.put(f"/api/sessions/{sid}/inputs", json={
            "original": "abcabcabc", "revised": "abcab", "labels": st["labels"]})
        assert r.status_code == 200
        assert r.json()["revision"] == rev + 1
        # 在途确认（携带旧 revision）被拒绝
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "stale_revision"
        # 旧选择也失效
        r = client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev, "selections": {"rep": {"choice": "discard"}}})
        assert r.status_code == 409

    def test_change_back_does_not_restore(self, client):
        st = create(client, "abc", "abc", [{"id": "a", "start": 0, "end": 1}])
        sid, rev = st["session_id"], st["revision"]
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200
        # 改成别的，再改回一模一样的内容
        client.put(f"/api/sessions/{sid}/inputs", json={
            "original": "abc", "revised": "abd", "labels": st["labels"]})
        r = client.put(f"/api/sessions/{sid}/inputs", json={
            "original": "abc", "revised": "abc", "labels": st["labels"]})
        assert r.json()["revision"] == rev + 2
        # 旧确认结果不可下载（属于旧 revision），需要重新确认
        assert client.get(f"/api/sessions/{sid}/download").status_code == 404
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 409
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev + 2})
        assert r.status_code == 200

    def test_result_removed_after_input_change(self, client):
        st = create(client, "abc", "abc", [{"id": "a", "start": 0, "end": 1}])
        sid, rev = st["session_id"], st["revision"]
        client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert client.get(f"/api/sessions/{sid}/download").status_code == 200
        client.put(f"/api/sessions/{sid}/inputs", json={
            "original": "abc", "revised": "ab", "labels": st["labels"]})
        assert client.get(f"/api/sessions/{sid}/download").status_code == 404


# ---------------- 综合场景 ----------------

class TestScenarios:
    def test_full_flow_mixed(self, client):
        # 自动 + 选择 + 无法保留 混合
        st = create(client, "中国人民银行abcabcabc", "中国人民银号abcabc",
                    [{"id": "country", "start": 0, "end": 4},
                     {"id": "bank", "start": 4, "end": 6},
                     {"id": "rep", "start": 9, "end": 12}])
        a = {l["id"]: l for l in st["analysis"]["labels"]}
        assert a["country"]["status"] == "auto"
        assert a["bank"]["status"] == "impossible"
        assert a["rep"]["status"] == "choice"
        assert a["rep"]["possible"] == [6, 9]
        sid, rev = st["session_id"], st["revision"]
        client.put(f"/api/sessions/{sid}/selections", json={
            "revision": rev,
            "selections": {"rep": {"choice": "position", "position": 9}}})
        r = client.post(f"/api/sessions/{sid}/confirm", json={"revision": rev})
        assert r.status_code == 200, r.text
        labels = {l["id"]: l for l in r.json()["result"]["labels"]}
        assert labels["country"]["start"] == 0 and labels["country"]["end"] == 4
        assert labels["rep"]["start"] == 9 and labels["rep"]["end"] == 12
        assert "bank" not in labels
        assert set(r.json()["result"]["meta"]["discarded"]) == {"bank"}

    def test_empty_everything(self, client):
        st = create(client, "", "", [])
        r = client.post(f"/api/sessions/{st['session_id']}/confirm",
                        json={"revision": st["revision"]})
        assert r.status_code == 200
        assert r.json()["result"]["labels"] == []
