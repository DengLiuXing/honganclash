import 'dart:async';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';

/// Signs in to the HongAn (红岸) panel and returns the subscription the panel
/// issues, or null when the user cancels.
Future<HonganSubscription?> showHonganImportDialog({BuildContext? context}) {
  return dialogs.showCommonDialog<HonganSubscription>(
    context: context,
    child: const _HonganImportDialog(key: ValueKey('hongan-import')),
  );
}

class _HonganImportDialog extends StatefulWidget {
  const _HonganImportDialog({super.key});

  @override
  State<_HonganImportDialog> createState() => _HonganImportDialogState();
}

class _HonganImportDialogState extends State<_HonganImportDialog> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _emailFocusNode = FocusNode();
  final _passwordFocusNode = FocusNode();

  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _emailFocusNode.dispose();
    _passwordFocusNode.dispose();
    super.dispose();
  }

  Future<void> _handleSubmit() async {
    if (_loading) {
      return;
    }
    final email = _emailController.text.trim();
    final password = _passwordController.text;
    if (email.isEmpty || password.isEmpty) {
      setState(() {
        _error = '请填写邮箱与密码';
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final session = await honganApi.login(email: email, password: password);
      final subscription = await honganApi.subscription(session);
      if (!mounted) {
        return;
      }
      Navigator.of(context).pop(subscription);
    } on HonganApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    return CommonDialog(
      title: '红岸账号导入',
      actions: [
        TextButton(
          onPressed: _loading
              ? null
              : () {
                  Navigator.of(context).pop();
                },
          child: Text(appLocalizations.cancel),
        ),
        TextButton(
          onPressed: _loading
              ? null
              : () {
                  unawaited(_handleSubmit());
                },
          child: Text(_loading ? '登录中…' : '登录并导入'),
        ),
      ],
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '登录红岸面板后自动添加订阅，节点与用量由面板下发。',
            style: AppTextStyle.subheadline.of(context),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _emailController,
            focusNode: _emailFocusNode,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            onSubmitted: (_) => _passwordFocusNode.requestFocus(),
            decoration: const InputDecoration(labelText: '邮箱'),
          ),
          const SizedBox(height: 8),
          SecretTextFormField(
            controller: _passwordController,
            focusNode: _passwordFocusNode,
            textInputAction: TextInputAction.done,
            onFieldSubmitted: (_) {
              unawaited(_handleSubmit());
            },
            decoration: const InputDecoration(labelText: '密码'),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
    );
  }
}
