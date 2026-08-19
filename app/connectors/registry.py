CONNECTORS = {}


def register_connector(connector_class):
    """
    Register a connector automatically.
    """

    CONNECTORS[
        connector_class.connector_name
    ] = connector_class

    return connector_class


def get_connector(name: str):
    """
    Return a connector class by name.
    """

    return CONNECTORS.get(name)


def get_all_connectors():
    """
    Return all registered connector classes.
    """

    return CONNECTORS.values()