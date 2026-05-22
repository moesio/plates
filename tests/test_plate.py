from webapp.webapp import _is_valid_plate


class TestPlateValidation:
    def test_mercosul_format(self):
        assert _is_valid_plate("ABC1A23") is True
        assert _is_valid_plate("XYZ9B99") is True
        assert _is_valid_plate("BRA2E19") is True

    def test_old_format(self):
        assert _is_valid_plate("ABC1234") is True
        assert _is_valid_plate("XYZ9999") is True
        assert _is_valid_plate("BRA2000") is True

    def test_with_hyphen(self):
        assert _is_valid_plate("ABC-1234") is True
        assert _is_valid_plate("ABC-1A23") is True

    def test_lowercase(self):
        assert _is_valid_plate("abc1a23") is True
        assert _is_valid_plate("abc1234") is True

    def test_with_spaces(self):
        assert _is_valid_plate("  ABC1A23  ") is True

    def test_too_short(self):
        assert _is_valid_plate("ABC123") is False
        assert _is_valid_plate("A1B2C3") is False

    def test_too_long(self):
        assert _is_valid_plate("ABCD1234") is False
        assert _is_valid_plate("ABCD1A234") is False

    def test_only_numbers(self):
        assert _is_valid_plate("1234567") is False

    def test_only_letters(self):
        assert _is_valid_plate("ABCDEFG") is False

    def test_invalid_mercosul_position(self):
        assert _is_valid_plate("ABC11A23") is False

    def test_empty(self):
        assert _is_valid_plate("") is False

    def test_special_chars(self):
        assert _is_valid_plate("ABC@1234") is False
