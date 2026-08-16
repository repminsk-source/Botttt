import config
import market


def main():
    expected = {"wood": 250, "iron": 600, "coal": 500, "oil": 1000, "uranium": 5000}
    assert config.RESOURCE_BUY_PRICE_GOLD == expected
    assert config.MARKET_PRICE_VARIANCE == 0.25
    for resource, base in expected.items():
        price = market.get_price(resource)
        assert int(base * 0.75) <= price <= int(base * 1.25) + 1
    print("MARKET_BALANCE_OK")


if __name__ == "__main__":
    main()
