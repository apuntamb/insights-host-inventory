import pytest

from tests.helpers.api_utils import assert_error_response
from tests.helpers.api_utils import assert_response_status
from tests.helpers.api_utils import build_facts_url
from tests.helpers.api_utils import build_host_id_list_for_url
from tests.helpers.api_utils import build_hosts_url
from tests.helpers.api_utils import get_id_list_from_hosts
from tests.helpers.db_utils import DB_FACTS
from tests.helpers.db_utils import DB_FACTS_NAMESPACE
from tests.helpers.db_utils import db_host
from tests.helpers.db_utils import DB_NEW_FACTS
from tests.helpers.db_utils import get_expected_facts_after_update
from tests.helpers.mq_utils import assert_patch_event_is_valid
from tests.helpers.test_utils import generate_uuid
from tests.helpers.test_utils import get_staleness_timestamps


@pytest.mark.parametrize(
    "patch_doc",
    [
        {"ansible_host": "NEW_ansible_host"},
        {"ansible_host": ""},
        {"display_name": "fred_flintstone"},
        {"display_name": "fred_flintstone", "ansible_host": "barney_rubble"},
    ],
)
def test_update_fields(patch_doc, event_producer_mock, db_create_host, db_get_host, api_patch):
    host = db_create_host()

    url = build_hosts_url(host_list_or_id=host.id)
    response_status, response_data = api_patch(url, patch_doc)

    assert_response_status(response_status, expected_status=200)

    record = db_get_host(host.id)

    for key in patch_doc:
        assert getattr(record, key) == patch_doc[key]


def test_patch_with_branch_id_parameter(event_producer_mock, db_create_multiple_hosts, api_patch):
    patch_doc = {"display_name": "branch_id_test"}

    hosts = db_create_multiple_hosts(how_many=5)

    url = build_hosts_url(host_list_or_id=hosts, query="?branch_id=123")
    response_status, response_data = api_patch(url, patch_doc)

    assert_response_status(response_status, expected_status=200)


def test_update_fields_on_multiple_hosts(event_producer_mock, db_create_multiple_hosts, db_get_hosts, api_patch):
    patch_doc = {"display_name": "fred_flintstone", "ansible_host": "barney_rubble"}

    hosts = db_create_multiple_hosts(how_many=5)

    url = build_hosts_url(host_list_or_id=hosts)
    response_status, response_data = api_patch(url, patch_doc)

    assert_response_status(response_status, expected_status=200)

    host_id_list = [host.id for host in hosts]
    hosts = db_get_hosts(host_id_list)

    for host in hosts:
        for key in patch_doc:
            assert getattr(host, key) == patch_doc[key]


def test_patch_on_non_existent_host(api_patch):
    non_existent_id = generate_uuid()

    patch_doc = {"ansible_host": "NEW_ansible_host"}

    url = build_hosts_url(host_list_or_id=non_existent_id)
    response_status, response_data = api_patch(url, patch_doc)

    assert_response_status(response_status, expected_status=404)


def test_patch_on_multiple_hosts_with_some_non_existent(event_producer_mock, db_create_host, api_patch):
    non_existent_id = generate_uuid()
    host = db_create_host()

    patch_doc = {"ansible_host": "NEW_ansible_host"}

    url = build_hosts_url(host_list_or_id=f"{non_existent_id},{host.id}")
    response_status, response_data = api_patch(url, patch_doc)

    assert_response_status(response_status, expected_status=200)


@pytest.mark.parametrize(
    "invalid_data",
    [{"ansible_host": "a" * 256}, {"ansible_host": None}, {}, {"display_name": None}, {"display_name": ""}],
)
def test_invalid_data(invalid_data, db_create_host, api_patch):
    host = db_create_host()

    url = build_hosts_url(host_list_or_id=host.id)
    response_status, response_data = api_patch(url, invalid_data)

    assert_response_status(response_status, expected_status=400)


def test_invalid_host_id(db_create_host, api_patch, subtests):
    host = db_create_host()

    patch_doc = {"display_name": "branch_id_test"}
    host_id_lists = ["notauuid", f"{host.id},notauuid"]

    for host_id_list in host_id_lists:
        with subtests.test(host_id_list=host_id_list):
            url = build_hosts_url(host_list_or_id=host_id_list)
            response_status, response_data = api_patch(url, patch_doc)
            assert_response_status(response_status, expected_status=400)


def test_patch_produces_update_event_no_request_id(
    event_datetime_mock, event_producer_mock, db_create_host, db_get_host, api_patch
):
    host = db_host()
    created_host = db_create_host(host)

    patch_doc = {"display_name": "patch_event_test"}

    url = build_hosts_url(host_list_or_id=created_host.id)
    response_status, response_data = api_patch(url, patch_doc)
    assert_response_status(response_status, expected_status=200)

    assert_patch_event_is_valid(
        host=created_host,
        event_producer=event_producer_mock,
        expected_request_id="-1",
        expected_timestamp=event_datetime_mock,
    )


def test_patch_produces_update_event_with_request_id(
    event_datetime_mock, event_producer_mock, db_create_host, db_get_host, api_patch
):
    patch_doc = {"display_name": "patch_event_test"}
    request_id = generate_uuid()
    headers = {"x-rh-insights-request-id": request_id}

    host = db_host()
    created_host = db_create_host(host)

    url = build_hosts_url(host_list_or_id=created_host.id)
    response_status, response_data = api_patch(url, patch_doc, extra_headers=headers)
    assert_response_status(response_status, expected_status=200)

    assert_patch_event_is_valid(
        host=created_host,
        event_producer=event_producer_mock,
        expected_request_id=request_id,
        expected_timestamp=event_datetime_mock,
    )


def test_patch_produces_update_event_no_insights_id(
    event_datetime_mock, event_producer_mock, db_create_host, db_get_host, api_patch
):
    host = db_host()
    del host.canonical_facts["insights_id"]

    created_host = db_create_host(host)

    patch_doc = {"display_name": "patch_event_test"}

    url = build_hosts_url(host_list_or_id=created_host.id)
    response_status, response_data = api_patch(url, patch_doc)
    assert_response_status(response_status, expected_status=200)

    assert_patch_event_is_valid(
        host=created_host,
        event_producer=event_producer_mock,
        expected_request_id="-1",
        expected_timestamp=event_datetime_mock,
    )


def test_event_producer_instrumentation(mocker, event_producer, future_mock, db_create_host, api_patch):
    created_host = db_create_host()
    patch_doc = {"display_name": "patch_event_test"}

    url = build_hosts_url(host_list_or_id=created_host.id)

    event_producer._kafka_producer.send.return_value = future_mock
    message_produced = mocker.patch("app.queue.event_producer.message_produced")
    message_not_produced = mocker.patch("app.queue.event_producer.message_not_produced")

    response_status, response_data = api_patch(url, patch_doc)
    assert_response_status(response_status, expected_status=200)

    for expected_callback, future_callbacks, fire_callbacks in (
        (message_produced, future_mock.callbacks, future_mock.success),
        (message_not_produced, future_mock.errbacks, future_mock.failure),
    ):
        assert len(future_callbacks) == 1
        assert future_callbacks[0].method == expected_callback

        fire_callbacks()
        args = future_callbacks[0].args + (future_callbacks[0].extra_arg,)
        expected_callback.assert_called_once_with(*args, **future_callbacks[0].kwargs)


def test_add_facts_without_fact_dict(api_patch, db_create_host):
    facts_url = build_facts_url(host_list_or_id=1, namespace=DB_FACTS_NAMESPACE)
    response_status, response_data = api_patch(facts_url, None)

    assert_error_response(response_data, expected_status=400, expected_detail="Request body is not valid JSON")


def test_add_facts_to_multiple_hosts(db_create_multiple_hosts, db_get_hosts, api_patch):
    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": DB_FACTS})

    host_id_list = get_id_list_from_hosts(created_hosts)
    facts_url = build_facts_url(host_list_or_id=created_hosts, namespace=DB_FACTS_NAMESPACE)

    response_status, response_data = api_patch(facts_url, DB_NEW_FACTS)

    assert_response_status(response_status, expected_status=200)

    expected_facts = get_expected_facts_after_update("add", DB_FACTS_NAMESPACE, DB_FACTS, DB_NEW_FACTS)

    assert all(host.facts == expected_facts for host in db_get_hosts(host_id_list))


def test_add_facts_to_multiple_hosts_with_branch_id(db_create_multiple_hosts, db_get_hosts, api_patch):
    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": DB_FACTS})

    host_id_list = get_id_list_from_hosts(created_hosts)
    facts_url = build_facts_url(host_list_or_id=created_hosts, namespace=DB_FACTS_NAMESPACE, query="?branch_id=1234")

    response_status, response_data = api_patch(facts_url, DB_NEW_FACTS)
    assert_response_status(response_status, expected_status=200)

    expected_facts = get_expected_facts_after_update("add", DB_FACTS_NAMESPACE, DB_FACTS, DB_NEW_FACTS)

    assert all(host.facts == expected_facts for host in db_get_hosts(host_id_list))


def test_add_facts_to_multiple_hosts_including_nonexistent_host(db_create_multiple_hosts, db_get_hosts, api_patch):
    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": DB_FACTS})

    url_host_id_list = f"{build_host_id_list_for_url(created_hosts)},{generate_uuid()},{generate_uuid()}"
    facts_url = build_facts_url(host_list_or_id=url_host_id_list, namespace=DB_FACTS_NAMESPACE)

    response_status, response_data = api_patch(facts_url, DB_NEW_FACTS)
    assert_response_status(response_status, expected_status=400)


def test_add_facts_to_multiple_hosts_overwrite_empty_key_value_pair(db_create_multiple_hosts, db_get_hosts, api_patch):
    facts = {DB_FACTS_NAMESPACE: {}}

    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": facts})

    host_id_list = get_id_list_from_hosts(created_hosts)
    facts_url = build_facts_url(host_list_or_id=created_hosts, namespace=DB_FACTS_NAMESPACE)

    response_status, response_data = api_patch(facts_url, DB_NEW_FACTS)
    assert_response_status(response_status, expected_status=200)

    expected_facts = get_expected_facts_after_update("add", DB_FACTS_NAMESPACE, facts, DB_NEW_FACTS)

    assert all(host.facts == expected_facts for host in db_get_hosts(host_id_list))


def test_add_facts_to_multiple_hosts_add_empty_fact_set(db_create_multiple_hosts, api_patch):
    new_facts = {}

    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": DB_FACTS})

    facts_url = build_facts_url(created_hosts, DB_FACTS_NAMESPACE)

    response_status, response_data = api_patch(facts_url, new_facts)
    assert_response_status(response_status, expected_status=400)


def test_add_facts_to_namespace_that_does_not_exist(db_create_multiple_hosts, api_patch):
    facts_namespace = "ns1"
    facts = {facts_namespace: {"key1": "value1"}}
    facts_to_update = {}

    created_hosts = db_create_multiple_hosts(how_many=2, extra_data={"facts": facts})

    facts_url = build_facts_url(host_list_or_id=created_hosts, namespace="imanonexistentnamespace")

    response_status, response_data = api_patch(facts_url, facts_to_update)
    assert_response_status(response_status, expected_status=400)


@pytest.mark.system_culling
def test_add_facts_to_multiple_culled_hosts(db_create_multiple_hosts, db_get_hosts, api_patch):
    staleness_timestamps = get_staleness_timestamps()

    created_hosts = db_create_multiple_hosts(
        how_many=2, extra_data={"facts": DB_FACTS, "stale_timestamp": staleness_timestamps["culled"]}
    )

    facts_url = build_facts_url(host_list_or_id=created_hosts, namespace=DB_FACTS_NAMESPACE)

    # Try to replace the facts on a host that has been marked as culled
    response_status, response_data = api_patch(facts_url, DB_NEW_FACTS)
    assert_response_status(response_status, expected_status=400)
