"""
REST+Json protocol implementation.
"""
import datetime
import decimal

from simplegeneric import generic

from wsme.protocols.rest import RestProtocol
import wsme.types

try:
    import simplejson as json
except ImportError:
    import json


@generic
def tojson(datatype, value):
    """
    A generic converter from python to jsonify-able datatypes.

    If a non-complex user specific type is to be used in the api,
    a specific tojson should be added::

        from wsme.protocol.restjson import tojson

        myspecialtype = object()

        @tojson.when_object(myspecialtype)
        def myspecialtype_tojson(datatype, value):
            return str(value)
    """
    if wsme.types.iscomplex(datatype):
        d = dict()
        for attr in wsme.types.list_attributes(datatype):
            d[attr.name] = tojson(attr.datatype, getattr(value, attr.key))
        return d
    elif wsme.types.isusertype(datatype):
        return tojson(datatype.basetype, datatype.tobasetype(value))
    return value


@tojson.when_type(list)
def array_tojson(datatype, value):
    if value is None:
        return None
    return [tojson(datatype[0], item) for item in value]


@tojson.when_object(decimal.Decimal)
def decimal_tojson(datatype, value):
    if value is None:
        return None
    return str(value)


@tojson.when_object(datetime.date)
def date_tojson(datatype, value):
    if value is None:
        return None
    return value.isoformat()


@tojson.when_object(datetime.time)
def time_tojson(datatype, value):
    if value is None:
        return None
    return value.isoformat()


@tojson.when_object(datetime.datetime)
def datetime_tojson(datatype, value):
    if value is None:
        return None
    return value.isoformat()


@generic
def fromjson(datatype, value):
    """
    A generic converter from json base types to python datatype.

    If a non-complex user specific type is to be used in the api,
    a specific fromjson should be added::

        from wsme.protocol.restjson import fromjson

        class MySpecialType(object):
            pass

        @fromjson.when_object(MySpecialType)
        def myspecialtype_fromjson(datatype, value):
            return MySpecialType(value)
    """
    if value is None:
        return None
    if wsme.types.iscomplex(datatype):
        obj = datatype()
        for attrdef in wsme.types.list_attributes(datatype):
            if attrdef.name in value:
                setattr(obj, attrdef.key,
                        fromjson(attrdef.datatype, value[attrdef.name]))
        return obj
    elif wsme.types.isusertype(datatype):
        value = datatype.frombasetype(
            fromjson(datatype.basetype, value))
    return value


@fromjson.when_type(list)
def array_fromjson(datatype, value):
    if value is None:
        return None
    return [fromjson(datatype[0], item) for item in value]


@fromjson.when_object(str)
def str_fromjson(datatype, value):
    if value is None:
        return None
    return str(value)


@fromjson.when_object(decimal.Decimal)
def decimal_fromjson(datatype, value):
    if value is None:
        return None
    return decimal.Decimal(value)


@fromjson.when_object(datetime.date)
def date_fromjson(datatype, value):
    if value is None:
        return None
    return datetime.datetime.strptime(value, '%Y-%m-%d').date()


@fromjson.when_object(datetime.time)
def time_fromjson(datatype, value):
    if value is None:
        return None
    return datetime.datetime.strptime(value, '%H:%M:%S').time()


@fromjson.when_object(datetime.datetime)
def datetime_fromjson(datatype, value):
    if value is None:
        return None
    return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')


class RestJsonProtocol(RestProtocol):
    """
    REST+Json protocol.

    .. autoattribute:: name
    .. autoattribute:: dataformat
    .. autoattribute:: content_types
    """

    name = 'restjson'
    dataformat = 'json'
    content_types = [
        'application/json',
        'application/javascript',
        'text/javascript',
         '']

    def decode_arg(self, value, arg):
        return fromjson(arg.datatype, value)

    def parse_arg(self, name, value):
        return json.loads(value)

    def parse_args(self, body):
        raw_args = json.loads(body)
        return raw_args

    def encode_result(self, context, result):
        r = tojson(context.funcdef.return_type, result)
        return json.dumps({'result': r}, ensure_ascii=False).encode('utf8')

    def encode_error(self, context, errordetail):
        return json.dumps(errordetail, encoding='utf-8')
