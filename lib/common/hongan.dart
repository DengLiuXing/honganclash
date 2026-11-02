import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/request.dart';

/// HongAn (红岸) panel endpoints.
///
/// The panel hands the desktop client its own `subscribe_url`, a plain
/// subscription link carrying the account token. That link no longer returns a
/// usable Clash config; the plaintext nodes come from `/user/server/fetch`.
/// The desktop client sends the raw JWT as the whole `Authorization` value; a
/// `Bearer` prefix is rejected.
const honganApiBaseUrl = 'http://hn.luoyaccc.com/api/v1';

const honganUserAgent = 'Mozilla/5.0 (dart:io) SuperAccelerator';

const honganNodeHost = 'hn.hngggg.top';

const honganNodeSni = 'down.xlkooiss.com';

const honganInfoPort = 27609;

class HonganApiException implements Exception {
  final String message;
  final int? statusCode;

  const HonganApiException(this.message, {this.statusCode});

  @override
  String toString() {
    return statusCode == null ? message : '$message ($statusCode)';
  }
}

/// What the panel returns for one successful login.
class HonganSession {
  final String email;

  /// Subscription token, already embedded in [HonganSubscription.subscribeUrl].
  final String subscriptionToken;

  /// Panel bearer, sent as the raw `Authorization` header.
  final String jwt;

  const HonganSession({
    required this.email,
    required this.subscriptionToken,
    required this.jwt,
  });
}

class HonganSubscription {
  final String subscribeUrl;
  final int upload;
  final int download;
  final int transferEnable;
  final DateTime? expiredAt;
  final String? planName;
  final String? uuid;
  final String jwt;

  const HonganSubscription({
    required this.subscribeUrl,
    this.upload = 0,
    this.download = 0,
    this.transferEnable = 0,
    this.expiredAt,
    this.planName,
    this.uuid,
    this.jwt = '',
  });

  int get used => upload + download;

  bool get hasQuota => transferEnable > 0;

  double get usedRatio {
    if (!hasQuota) {
      return 0;
    }
    return (used / transferEnable).clamp(0.0, 1.0);
  }

  bool get isExpired {
    final expiredAt = this.expiredAt;
    return expiredAt != null && expiredAt.isBefore(DateTime.now());
  }
}

class HonganApi {
  HonganApi._();

  Future<HonganSession> login({
    required String email,
    required String password,
  }) async {
    final body = await _request(
      '/passport/auth/login',
      method: 'POST',
      body: {'email': email, 'password': password},
    );
    final data = _dataOf(body);
    final subscriptionToken = _stringOf(data['token']);
    final jwt = _stringOf(data['auth_data']);
    if (subscriptionToken == null || jwt == null) {
      throw const HonganApiException('面板未返回登录凭证');
    }
    return HonganSession(
      email: email,
      subscriptionToken: subscriptionToken,
      jwt: jwt,
    );
  }

  Future<HonganSubscription> subscription(HonganSession session) async {
    final body = await _request('/user/getSubscribe', jwt: session.jwt);
    final data = _dataOf(body);
    final subscribeUrl = _stringOf(data['subscribe_url']);
    if (subscribeUrl == null) {
      throw const HonganApiException('面板未返回订阅地址，账号可能已到期');
    }
    // Some panel versions keep the quota and uuid only on /user/info.
    final info = _dataOf(await _request('/user/info', jwt: session.jwt));
    final upload = _intOf(data['u']);
    final download = _intOf(data['d']);
    final transferEnable = _intOf(data['transfer_enable']);
    final plan = data['plan'] ?? info['plan'];
    return HonganSubscription(
      subscribeUrl: subscribeUrl,
      upload: upload == 0 ? _intOf(info['u']) : upload,
      download: download == 0 ? _intOf(info['d']) : download,
      transferEnable: transferEnable == 0
          ? _intOf(info['transfer_enable'])
          : transferEnable,
      expiredAt: _dateOf(data['expired_at']) ?? _dateOf(info['expired_at']),
      planName: plan is Map ? _stringOf(plan['name']) : null,
      uuid: _stringOf(data['uuid']) ?? _stringOf(info['uuid']),
      jwt: session.jwt,
    );
  }

  /// Panel-maintained plaintext node table; the subscription URL itself now
  /// returns an encrypted body that a standard Clash client cannot parse.
  Future<List<HonganServer>> servers({required String jwt}) async {
    final body = await _request('/user/server/fetch', jwt: jwt);
    final data = body['data'];
    final raw = data is List ? data : (data is Map ? data['servers'] : null);
    if (raw is! List) {
      throw const HonganApiException('面板未返回节点列表');
    }
    final servers = <HonganServer>[];
    for (final item in raw) {
      if (item is! Map) {
        continue;
      }
      final json = item.map<String, Object?>(
        (key, value) => MapEntry('$key', value),
      );
      final server = HonganServer.tryParse(json);
      if (server != null) {
        servers.add(server);
      }
    }
    servers.sort((a, b) => a.port.compareTo(b.port));
    return servers;
  }

  Future<Map<String, Object?>> _request(
    String path, {
    String method = 'GET',
    Map<String, Object?>? body,
    String? jwt,
  }) async {
    final Response<Object?> response;
    try {
      response = await request.dio.request<Object?>(
        '$honganApiBaseUrl$path',
        data: body == null ? null : json.encode(body),
        options: Options(
          method: method,
          contentType: body == null ? null : Headers.jsonContentType,
          responseType: ResponseType.json,
          validateStatus: (_) => true,
          headers: {
            Headers.acceptHeader: Headers.jsonContentType,
            HttpHeaders.userAgentHeader: honganUserAgent,
            HttpHeaders.authorizationHeader: ?jwt,
          },
        ),
      );
    } on DioException catch (error) {
      throw HonganApiException(_networkMessageOf(error));
    }
    final data = response.data;
    final result = data is Map
        ? data.map((key, value) => MapEntry('$key', value))
        : <String, Object?>{};
    final statusCode = response.statusCode;
    if (statusCode != null && statusCode >= 200 && statusCode < 300) {
      return result;
    }
    throw HonganApiException(
      _messageOf(result, statusCode),
      statusCode: statusCode,
    );
  }
}

final honganApi = HonganApi._();

class HonganServer {
  final String name;
  final String host;
  final int port;
  final String serverName;
  final bool insecure;

  const HonganServer({
    required this.name,
    required this.host,
    required this.port,
    required this.serverName,
    required this.insecure,
  });

  static HonganServer? tryParse(Map<String, Object?> json) {
    if ((_stringOf(json['type']) ?? '').toLowerCase() != 'anytls') {
      return null;
    }
    final online = json['is_online'];
    if (online == false || online == 0 || online == '0') {
      return null;
    }
    final port = _intOf(json['port']);
    if (port <= 0 || port == honganInfoPort) {
      return null;
    }
    return HonganServer(
      name: _stringOf(json['name']) ?? '节点$port',
      host: _stringOf(json['host']) ?? honganNodeHost,
      port: port,
      serverName: _stringOf(json['server_name']) ?? honganNodeSni,
      insecure: json['insecure'] == true || _intOf(json['insecure']) != 0,
    );
  }
}

String buildHonganConfig({
  required List<HonganServer> servers,
  required String uuid,
}) {
  final names = <String>[];
  final usedNames = <String>{};
  for (final server in servers) {
    var name = server.name;
    if (!usedNames.add(name)) {
      name = '${server.name} (${server.port})';
      var suffix = 2;
      while (!usedNames.add(name)) {
        name = '${server.name} (${server.port}-$suffix)';
        suffix++;
      }
    }
    names.add(name);
  }

  final buffer = StringBuffer()
    ..writeln('mixed-port: 7890')
    ..writeln('allow-lan: false')
    ..writeln('bind-address: "*"')
    ..writeln('mode: rule')
    ..writeln('log-level: info')
    ..writeln('ipv6: false')
    ..writeln('unified-delay: true')
    ..writeln('tcp-concurrent: true')
    ..writeln('find-process-mode: always')
    ..writeln('keep-alive-interval: 30')
    ..writeln('geodata-loader: memconservative')
    ..writeln('external-controller: 127.0.0.1:9090')
    ..writeln()
    ..writeln('dns:')
    ..writeln('  enable: true')
    ..writeln('  ipv6: false')
    ..writeln('  enhanced-mode: fake-ip')
    ..writeln('  fake-ip-range: 198.18.0.1/16')
    ..writeln('  fake-ip-filter:')
    ..writeln('    - "*.lan"')
    ..writeln('    - localhost.ptlogin2.qq.com')
    ..writeln('  default-nameserver: [223.5.5.5, 119.29.29.29]')
    ..writeln(
      '  nameserver: ["https://doh.pub/dns-query", '
      '"https://dns.alidns.com/dns-query"]',
    )
    ..writeln('  fallback: ["tls://8.8.4.4", "tls://1.1.1.1"]')
    ..writeln('  proxy-server-nameserver: ["https://doh.pub/dns-query"]')
    ..writeln(
      '  fallback-filter: { geoip: true, geoip-code: CN, '
      'geosite: [gfw], ipcidr: [240.0.0.0/4] }',
    )
    ..writeln()
    ..writeln('proxies:');

  for (var i = 0; i < servers.length; i++) {
    final server = servers[i];
    final host = server.host.isEmpty ? honganNodeHost : server.host;
    final serverName = server.serverName.isEmpty
        ? honganNodeSni
        : server.serverName;
    buffer
      ..writeln('  - name: ${jsonEncode(names[i])}')
      ..writeln('    type: anytls')
      ..writeln('    server: ${jsonEncode(host)}')
      ..writeln('    port: ${server.port}')
      ..writeln('    password: ${jsonEncode(uuid)}')
      ..writeln('    client-fingerprint: chrome')
      ..writeln('    udp: true')
      ..writeln('    alpn: [h2, http/1.1]')
      ..writeln('    sni: ${jsonEncode(serverName)}')
      ..writeln('    skip-cert-verify: ${server.insecure}');
  }

  buffer
    ..writeln()
    ..writeln('proxy-groups:')
    ..writeln('  - name: 自动选择')
    ..writeln('    type: url-test')
    ..writeln('    url: http://cp.cloudflare.com/generate_204')
    ..writeln('    interval: 300')
    ..writeln('    tolerance: 50')
    ..writeln('    proxies:');
  for (final name in names) {
    buffer.writeln('      - ${jsonEncode(name)}');
  }
  buffer
    ..writeln('  - name: 手动选择')
    ..writeln('    type: select')
    ..writeln('    proxies:')
    ..writeln('      - 自动选择');
  for (final name in names) {
    buffer.writeln('      - ${jsonEncode(name)}');
  }
  buffer
    ..writeln('      - DIRECT')
    ..writeln('  - name: 红岸云')
    ..writeln('    type: select')
    ..writeln('    proxies:')
    ..writeln('      - 手动选择')
    ..writeln('      - 自动选择')
    ..writeln('      - DIRECT')
    ..writeln('  - name: 漏网之鱼')
    ..writeln('    type: select')
    ..writeln('    proxies:')
    ..writeln('      - 手动选择')
    ..writeln('      - DIRECT')
    ..writeln()
    ..writeln('rules:')
    ..writeln('  - DOMAIN-SUFFIX,local,DIRECT')
    ..writeln('  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve')
    ..writeln('  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve')
    ..writeln('  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve')
    ..writeln('  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve')
    ..writeln('  - IP-CIDR6,fc00::/7,DIRECT,no-resolve')
    ..writeln('  - GEOSITE,cn,DIRECT')
    ..writeln('  - GEOIP,CN,DIRECT')
    ..writeln('  - MATCH,漏网之鱼');
  return buffer.toString();
}

Map<String, Object?> _dataOf(Map<String, Object?> body) {
  final data = body['data'];
  if (data is Map) {
    return data.map((key, value) => MapEntry('$key', value));
  }
  throw const HonganApiException('面板响应缺少 data');
}

String _messageOf(Map<String, Object?> body, int? statusCode) {
  final message = _stringOf(body['message']);
  if (message != null) {
    return message;
  }
  final errors = body['errors'];
  if (errors is Map && errors.isNotEmpty) {
    final first = errors.values.first;
    if (first is List && first.isNotEmpty) {
      return '${first.first}';
    }
  }
  return '面板返回 HTTP $statusCode';
}

String _networkMessageOf(DioException error) {
  return switch (error.type) {
    DioExceptionType.connectionTimeout ||
    DioExceptionType.sendTimeout ||
    DioExceptionType.receiveTimeout => '连接面板超时，请检查网络',
    DioExceptionType.badCertificate => '面板证书校验失败',
    DioExceptionType.connectionError => '无法连接面板服务器',
    _ => '请求失败：${error.message ?? error.type.name}',
  };
}

String? _stringOf(Object? value) {
  if (value is String && value.isNotEmpty) {
    return value;
  }
  return null;
}

int _intOf(Object? value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value) ?? 0;
  }
  return 0;
}

DateTime? _dateOf(Object? value) {
  if (value is int && value > 0) {
    return DateTime.fromMillisecondsSinceEpoch(value * 1000);
  }
  if (value is String && value.isNotEmpty) {
    return DateTime.tryParse(value);
  }
  return null;
}
