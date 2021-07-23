# -*- coding: utf-8 -*-
import pytest

from nameko_slackclient import constants


@pytest.fixture
def config():
    return {constants.CONFIG_KEY: {"TOKEN": "abc-123"}}
