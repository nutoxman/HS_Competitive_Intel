from engine.core.run import hello_engine

def test_engine_smoke():
    assert hello_engine() == "engine scaffold ok"

