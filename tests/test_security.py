from core.security import is_affirmative, is_negative, redact


def test_redact_hides_key_phone_and_long_numbers():
    text = "key=sk-abcdef123456 phone=13812345678 order=2026101912345678"
    result = redact(text)
    assert "sk-abcdef123456" not in result
    assert "13812345678" not in result
    assert "2026101912345678" not in result


def test_affirmative_and_negative_replies():
    assert is_affirmative("确认")
    assert is_affirmative("好的！")
    assert is_affirmative("我确认。")
    assert not is_affirmative("确认一下价格")

    assert is_negative("取消")
    assert is_negative("算了。")
    assert not is_negative("不要退款，改成退货")
