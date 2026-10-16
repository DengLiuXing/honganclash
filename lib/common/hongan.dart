import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/request.dart';

/// HongAn (红岸) panel endpoints.
///
/// The panel hands the desktop client its own `subscribe_url`, a plain
/// subscription link carrying the account token. The desktop client sends the
/// raw JWT as the whole `Authorization` value; a `Bearer` prefix is rejected.
const honganApiBaseUrl = 'http://hn.luoyaccc.com/api/v1';

const honganUserAgent = 'Dart/3.9 (dart:io)';

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

  const HonganSubscription({
    required this.subscribeUrl,
    this.upload = 0,
    this.download = 0,
    this.transferEnable = 0,
    this.expiredAt,
    this.planName,
    this.uuid,
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
    final plan = data['plan'];
    return HonganSubscription(
      subscribeUrl: subscribeUrl,
      upload: _intOf(data['u']),
      download: _intOf(data['d']),
      transferEnable: _intOf(data['transfer_enable']),
      expiredAt: _dateOf(data['expired_at']),
      planName: plan is Map ? _stringOf(plan['name']) : null,
      uuid: _stringOf(data['uuid']),
    );
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
            if (jwt != null) HttpHeaders.authorizationHeader: jwt,
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
