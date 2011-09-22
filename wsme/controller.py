import inspect
import traceback
import weakref
import logging
import webob
import sys

from wsme import exc
from wsme.types import register_type

__all__ = ['expose', 'validate', 'WSRoot']

log = logging.getLogger(__name__)

registered_protocols = {}


html_body = """
<html>
<head>
  <style type='text/css'>
    %(css)s
  </style>
</head>
<body>
%(content)s
</body>
</html>
"""


def scan_api(controller, path=[]):
    for name in dir(controller):
        if name.startswith('_'):
            continue
        a = getattr(controller, name)
        if hasattr(a, '_wsme_definition'):
            yield path, a._wsme_definition
        else:
            for i in scan_api(a, path + [name]):
                yield i


class FunctionArgument(object):
    def __init__(self, name, datatype, mandatory, default):
        self.name = name
        self.datatype = datatype
        self.mandatory = mandatory
        self.default = default


class FunctionDefinition(object):
    def __init__(self, func):
        self.name = func.__name__
        self.return_type = None
        self.arguments = []
        self.protocol_specific = False
        self.contenttype = None

    @classmethod
    def get(cls, func):
        fd = getattr(func, '_wsme_definition', None)
        if fd is None:
            fd = FunctionDefinition(func)
            func._wsme_definition = fd
        return fd


def register_protocol(protocol):
    global registered_protocols
    registered_protocols[protocol.name] = protocol


class expose(object):
    def __init__(self, return_type=None):
        self.return_type = return_type
        register_type(return_type)

    def __call__(self, func):
        fd = FunctionDefinition.get(func)
        fd.return_type = self.return_type
        return func


class pexpose(object):
    def __init__(self, return_type=None, contenttype=None):
        self.return_type = return_type
        self.contenttype = contenttype
        register_type(return_type)

    def __call__(self, func):
        fd = FunctionDefinition.get(func)
        fd.return_type = self.return_type
        fd.protocol_specific = True
        fd.contenttype = self.contenttype
        return func

class validate(object):
    def __init__(self, *args, **kw):
        self.param_types = args

    def __call__(self, func):
        fd = FunctionDefinition.get(func)
        args, varargs, keywords, defaults = inspect.getargspec(func)
        if args[0] == 'self':
            args = args[1:]
        for i, argname in enumerate(args):
            datatype = self.param_types[i]
            mandatory = defaults is None or i <= len(defaults)
            default = None
            if not mandatory:
                default = defaults[i - (len(args) - len(defaults))]
            fd.arguments.append(FunctionArgument(argname, datatype,
                                                 mandatory, default))
        return func


class WSRoot(object):
    def __init__(self, protocols=None):
        self._debug = True
        if protocols is None:
            protocols = registered_protocols.keys()
        self.protocols = {}
        for protocol in protocols:
            if isinstance(protocol, str):
                protocol = registered_protocols[protocol]()
            self.protocols[protocol.name] = protocol

    def _select_protocol(self, request):
        protocol = None
        if 'wsmeproto' in request.params:
            protocol = self.protocols[request.params['wsmeproto']]
        else:
            for p in self.protocols.values():
                if p.accept(self, request):
                    protocol = p
                    break
        return protocol

    def _handle_request(self, request):
        res = webob.Response()
        res_content_type = None
        try:
            protocol = self._select_protocol(request)
            if protocol is None:
                msg = ("None of the following protocols can handle this "
                       "request : %s" % ','.join(self.protocols.keys()))
                res.status = 500
                res.text = msg
                log.error(msg)
                return res
            path = protocol.extract_path(request)
            func, funcdef = self._lookup_function(path)
            kw = protocol.read_arguments(request,
                funcdef and funcdef.arguments or None)

            result = func(**kw)

            res.status = 200

            if funcdef.protocol_specific and funcdef.return_type is None:
                res.body = result
            else:
                # TODO make sure result type == a._wsme_definition.return_type
                res.body = protocol.encode_result(result, funcdef.return_type)
            res_content_type = funcdef.contenttype
        except Exception, e:
            infos = self._format_exception(sys.exc_info())
            log.error(str(infos))
            res.status = 500
            res.body = protocol.encode_error(infos)

        if res_content_type is None:
            # Attempt to correctly guess what content-type we should return.
            last_q = 0
            if hasattr(request.accept, '_parsed'):
                for mimetype, q in request.accept._parsed:
                    if mimetype in protocol.content_types and last_q < q:
                        res_content_type = mimetype
            else:
                res_content_type = request.accept.best_match([
                    ct for ct in protocol.content_types if ct])

        # If not we will attempt to convert the body to an accepted
        # output format.
        if res_content_type is None:
            if "text/html" in request.accept:
                res.body = self._html_format(res.body, protocol.content_types)
                res_content_type = "text/html"

        # TODO should we consider the encoding asked by
        # the web browser ?
        res.headers['Content-Type'] = "%s; charset=UTF-8" % res_content_type

        return res

    def _lookup_function(self, path):
        a = self

        isprotocol_specific = path[0] == '_protocol'
        
        if isprotocol_specific:
            a = self.protocols[path[1]]
            path = path[2:]

        print path, a, a.api_wsdl

        for name in path:
            a = getattr(a, name, None)
            if a is None:
                break

        print a

        if not hasattr(a, '_wsme_definition'):
            raise exc.UnknownFunction('/'.join(path))

        definition = a._wsme_definition

        return a, definition

    def _format_exception(self, excinfo):
        """Extract informations that can be sent to the client."""
        if isinstance(excinfo[1], exc.ClientSideError):
            r = dict(faultcode="Client",
                     faultstring=unicode(excinfo[1]))
            log.warning("Client-side error: %s" % r['faultstring'])
            return r
        else:
            faultstring = str(excinfo[1])
            debuginfo = "\n".join(traceback.format_exception(*excinfo))

            log.error('Server-side error: "%s". Detail: \n%s' % (
                faultstring, debuginfo))

            r = dict(faultcode="Server", faultstring=faultstring)
            if self._debug:
                r['debuginfo'] = debuginfo
            return r

    def _html_format(self, content, content_types):
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_for_mimetype
            from pygments.formatters import HtmlFormatter

            lexer = None
            for ct in content_types:
                try:
                    print ct
                    lexer = get_lexer_for_mimetype(ct)
                    break
                except:
                    pass

            if lexer is None:
                raise ValueError("No lexer found")
            formatter = HtmlFormatter()
            return html_body % dict(
                css=formatter.get_style_defs(),
                content=highlight(content, lexer, formatter).encode('utf8'))
        except Exception, e:
            log.warning(
                "Could not pygment the content because of the following "
                "error :\n%s" % e)
            return html_body % dict(
                css='',
                content='<pre>%s</pre>' %
                    content.replace('>', '&gt;').replace('<', '&lt;'))
