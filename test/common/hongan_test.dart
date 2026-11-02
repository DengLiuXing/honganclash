import 'package:fl_clash/common/hongan.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('HonganServer.tryParse', () {
    test('keeps an online anytls node', () {
      final server = HonganServer.tryParse(<String, Object?>{
        'name': '香港1',
        'type': 'anytls',
        'host': 'hn.hngggg.top',
        'port': 27611,
        'server_name': 'down.xlkooiss.com',
        'insecure': 1,
        'is_online': 1,
      });

      expect(server, isNotNull);
      expect(server!.name, '香港1');
      expect(server.host, 'hn.hngggg.top');
      expect(server.port, 27611);
      expect(server.serverName, 'down.xlkooiss.com');
      expect(server.insecure, isTrue);
    });

    test('falls back to the shared node host and SNI', () {
      final server = HonganServer.tryParse(<String, Object?>{
        'type': 'anytls',
        'port': 27612,
        'is_online': 1,
      });

      expect(server, isNotNull);
      expect(server!.name, '节点27612');
      expect(server.host, honganNodeHost);
      expect(server.serverName, honganNodeSni);
      expect(server.insecure, isFalse);
    });

    test('drops offline, info and non-anytls rows', () {
      expect(
        HonganServer.tryParse(<String, Object?>{
          'type': 'anytls',
          'port': 27611,
          'is_online': 0,
        }),
        isNull,
      );
      expect(
        HonganServer.tryParse(<String, Object?>{
          'type': 'anytls',
          'port': honganInfoPort,
          'is_online': 1,
        }),
        isNull,
      );
      expect(
        HonganServer.tryParse(<String, Object?>{
          'type': 'trojan',
          'port': 27611,
          'is_online': 1,
        }),
        isNull,
      );
    });
  });

  test('buildHonganConfig writes nodes, groups and rules', () {
    final config = buildHonganConfig(
      servers: const [
        HonganServer(
          name: '香港1',
          host: 'hn.hngggg.top',
          port: 27611,
          serverName: 'down.xlkooiss.com',
          insecure: false,
        ),
        HonganServer(
          name: '香港1',
          host: 'hn.hngggg.top',
          port: 27612,
          serverName: 'down.xlkooiss.com',
          insecure: true,
        ),
      ],
      uuid: 'uuid-1',
    );

    expect(config, contains('  - name: "香港1"'));
    expect(config, contains('  - name: "香港1 (27612)"'));
    expect(config, contains('password: "uuid-1"'));
    expect(config, contains('skip-cert-verify: true'));
    expect(config, contains('  - name: 自动选择'));
    expect(config, contains('MATCH,漏网之鱼'));
  });
}
