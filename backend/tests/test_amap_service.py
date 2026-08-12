import asyncio
from datetime import date

from app.config import Settings
from app.schemas.domain import Attraction, Hotel, Location, Meal
from app.services.amap_service import AmapMCPService
from app.services.amap_service import build_map_points


def make_settings() -> Settings:
    return Settings(_env_file=None, AMAP_MAPS_API_KEY="test-key")


class FakeMCPClient:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return self.responses[name]


def test_settings_use_real_amap_mcp_stdio_defaults_and_api_key_name() -> None:
    settings = make_settings()

    assert settings.amap_api_key == "test-key"
    assert settings.amap_mcp_command == "amap-mcp-server"
    assert settings.amap_mcp_args == ""


def test_search_attractions_uses_maps_text_search_and_normalizes_pois() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_text_search": {
                "pois": [
                    {
                        "id": "B000A8UIN8",
                        "name": "故宫博物院",
                        "cityname": "北京市",
                        "address": "景山前街4号",
                        "location": "116.397128,39.916527",
                        "type": "风景名胜;博物馆",
                        "biz_ext": {"rating": "4.8", "cost": "60"},
                    }
                ]
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    attractions = asyncio.run(service.search_attractions(keywords="故宫", city="北京"))

    assert fake_client.calls == [
        ("maps_text_search", {"keywords": "故宫", "city": "北京", "citylimit": "true"})
    ]
    assert attractions[0].name == "故宫博物院"
    assert attractions[0].city == "北京市"
    assert attractions[0].location is not None
    assert attractions[0].location.longitude == 116.397128
    assert attractions[0].location.latitude == 39.916527
    assert attractions[0].rating == 4.8
    assert attractions[0].ticket_price == 60
    assert attractions[0].poi_id == "B000A8UIN8"
    assert attractions[0].source == "amap"


def test_search_hotels_uses_maps_text_search_and_normalizes_candidates() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_text_search": {
                "pois": [
                    {
                        "id": "H001",
                        "name": "北京测试酒店",
                        "cityname": "北京市",
                        "address": "测试路1号",
                        "location": "116.400000,39.900000",
                        "type": "住宿服务;宾馆酒店",
                        "distance": "1200",
                        "biz_ext": {"rating": "4.6", "cost": "520"},
                    }
                ]
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    hotels = asyncio.run(service.search_hotels(keywords="酒店", city="北京"))

    assert fake_client.calls == [
        ("maps_text_search", {"keywords": "酒店", "city": "北京", "citylimit": "true"})
    ]
    assert hotels[0].name == "北京测试酒店"
    assert hotels[0].rating == 4.6
    assert hotels[0].estimated_cost == 520
    assert hotels[0].distance == "1200"
    assert hotels[0].source == "amap"


def test_search_hotels_filters_out_non_lodging_pois() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_text_search": {
                "pois": [
                    {
                        "id": "SCENIC001",
                        "name": "杭州西湖风景名胜区",
                        "cityname": "杭州市",
                        "address": "西湖街道龙井路1号",
                        "location": "120.130000,30.260000",
                        "type": "风景名胜;风景名胜;国家级景点",
                        "biz_ext": {"rating": "4.9"},
                    },
                    {
                        "id": "HOTEL001",
                        "name": "杭州测试酒店",
                        "cityname": "杭州市",
                        "address": "测试路1号",
                        "location": "120.160000,30.250000",
                        "type": "住宿服务;宾馆酒店;宾馆酒店",
                        "typecode": "100100",
                        "biz_ext": {"rating": "4.6", "cost": "600"},
                    },
                ]
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    hotels = asyncio.run(service.search_hotels(keywords="西湖 酒店", city="杭州"))

    assert [hotel.name for hotel in hotels] == ["杭州测试酒店"]
    assert all("风景名胜" not in hotel.type for hotel in hotels)


def test_get_weather_uses_maps_weather_and_normalizes_forecast_casts() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_weather": {
                "forecasts": [
                    {
                        "city": "北京市",
                        "casts": [
                            {
                                "date": "2026-06-10",
                                "dayweather": "晴",
                                "nightweather": "多云",
                                "daytemp": "28",
                                "nighttemp": "18",
                                "daywind": "东",
                                "daypower": "≤3",
                            }
                        ],
                    }
                ]
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    weather = asyncio.run(service.get_weather(city="北京"))

    assert fake_client.calls == [("maps_weather", {"city": "北京"})]
    assert weather[0].city == "北京市"
    assert weather[0].date == date(2026, 6, 10)
    assert weather[0].day_weather == "晴"
    assert weather[0].night_weather == "多云"
    assert weather[0].day_temp == 28
    assert weather[0].night_temp == 18
    assert weather[0].wind_direction == "东"
    assert weather[0].wind_power == "≤3"


def test_get_weather_normalizes_amap_mcp_top_level_forecasts() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_weather": {
                "city": "北京市",
                "forecasts": [
                    {
                        "date": "2026-06-01",
                        "dayweather": "多云",
                        "nightweather": "阴",
                        "daytemp": "34",
                        "nighttemp": "18",
                        "daywind": "南",
                        "daypower": "1-3",
                    }
                ],
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    weather = asyncio.run(service.get_weather(city="北京"))

    assert len(weather) == 1
    assert weather[0].city == "北京市"
    assert weather[0].date == date(2026, 6, 1)
    assert weather[0].day_weather == "多云"


def test_get_route_summary_uses_address_direction_tool_and_drops_detailed_steps() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_direction_driving_by_address": {
                "route": {
                    "paths": [
                        {
                            "distance": "12500",
                            "duration": "1800",
                            "steps": [{"instruction": "沿测试路行驶"}],
                        }
                    ]
                }
            }
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    summary = asyncio.run(
        service.get_route_summary(
            origin_address="故宫博物院",
            destination_address="颐和园",
            mode="driving",
            origin_city="北京",
            destination_city="北京",
        )
    )

    assert fake_client.calls == [
        (
            "maps_direction_driving_by_address",
            {
                "origin_address": "故宫博物院",
                "destination_address": "颐和园",
                "origin_city": "北京",
                "destination_city": "北京",
            },
        )
    ]
    assert summary == {
        "route_distance_km": 12.5,
        "route_duration_minutes": 30,
        "transit_method": "driving",
    }


def test_search_attractions_enriches_missing_location_from_poi_detail() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_text_search": {
                "pois": [
                    {
                        "id": "POI001",
                        "name": "Palace Museum",
                        "address": "Jingshan Front Street 4",
                        "typecode": "110201",
                    }
                ]
            },
            "maps_search_detail": {
                "id": "POI001",
                "name": "Palace Museum",
                "city": "Beijing",
                "address": "Jingshan Front Street 4",
                "location": "116.397128,39.916527",
                "type": "Scenic spot",
                "rating": "4.8",
            },
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    attractions = asyncio.run(service.search_attractions(keywords="Palace", city="Beijing"))

    assert fake_client.calls == [
        ("maps_text_search", {"keywords": "Palace", "city": "Beijing", "citylimit": "true"}),
        ("maps_search_detail", {"id": "POI001"}),
    ]
    assert attractions[0].city == "Beijing"
    assert attractions[0].location is not None
    assert attractions[0].location.longitude == 116.397128
    assert attractions[0].location.latitude == 39.916527
    assert attractions[0].rating == 4.8


def test_search_hotels_falls_back_to_maps_geo_when_detail_has_no_location() -> None:
    fake_client = FakeMCPClient(
        {
            "maps_text_search": {
                "pois": [
                    {
                        "id": "HOTEL001",
                        "name": "Central Hotel",
                        "address": "Central Street 1",
                        "typecode": "100100",
                    }
                ]
            },
            "maps_search_detail": {
                "id": "HOTEL001",
                "name": "Central Hotel",
                "city": "Beijing",
                "address": "Central Street 1",
                "type": "Hotel",
                "cost": "520",
            },
            "maps_geo": {
                "return": [
                    {
                        "city": "Beijing",
                        "location": "116.400000,39.900000",
                        "level": "门牌号",
                    }
                ]
            },
        }
    )
    service = AmapMCPService(settings=make_settings(), client=fake_client)

    hotels = asyncio.run(service.search_hotels(keywords="Hotel", city="Beijing"))

    assert fake_client.calls == [
        ("maps_text_search", {"keywords": "Hotel", "city": "Beijing", "citylimit": "true"}),
        ("maps_search_detail", {"id": "HOTEL001"}),
        ("maps_geo", {"address": "Central Street 1", "city": "Beijing"}),
    ]
    assert hotels[0].location is not None
    assert hotels[0].location.longitude == 116.4
    assert hotels[0].location.latitude == 39.9
    assert hotels[0].estimated_cost == 520


def test_build_map_points_only_uses_entities_with_locations() -> None:
    points = build_map_points(
        day_index=0,
        attractions=[
            Attraction(
                name="Palace Museum",
                location=Location(longitude=116.397128, latitude=39.916527),
            ),
            Attraction(name="No Coordinate Attraction"),
        ],
        hotel=Hotel(
            name="Central Hotel",
            location=Location(longitude=116.4, latitude=39.9),
        ),
        meals=[
            Meal(
                type="lunch",
                name="Lunch Place",
                location=Location(longitude=116.41, latitude=39.91),
            ),
            Meal(type="dinner", name="No Coordinate Dinner"),
        ],
    )

    assert [point.name for point in points] == ["Palace Museum", "Central Hotel", "Lunch Place"]
    assert [point.point_type for point in points] == ["attraction", "hotel", "meal"]
    assert [point.order_index for point in points] == [0, 1, 2]
    assert all(point.day_index == 0 for point in points)
