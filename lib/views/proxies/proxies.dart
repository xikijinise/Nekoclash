import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/proxies/list.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_parsing/path_parsing.dart';

import 'setting.dart';
import 'tab.dart';

class ProxiesView extends ConsumerStatefulWidget {
  const ProxiesView({super.key, this.picker = false});

  /// Leaves the bar only its search and delay test, for picking a proxy from a
  /// sheet.
  final bool picker;

  @override
  ConsumerState<ProxiesView> createState() => _ProxiesViewState();
}

class _ProxiesViewState extends ConsumerState<ProxiesView> {
  final GlobalKey<ProxiesTabViewState> _proxiesTabKey = GlobalKey();

  // The same instance on every build, so the bar changing with the current
  // group or its delay test leaves the page alone.
  late final _tabView = ProxiesTabView(key: _proxiesTabKey);
  bool _isTab = false;

  List<CommonPopupMenuItem> _buildMenuItems(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    return [
      CommonPopupMenuItem(
        glyph: AppGlyphs.sliders,
        label: appLocalizations.settings,
        onPressed: () {
          showSheet(
            context: context,
            builder: (_) {
              return CommonScaffold(
                body: const ProxiesSetting(),
                title: appLocalizations.settings,
              );
            },
          );
        },
      ),
    ];
  }

  IconButtonData? _buildPrimaryAction(bool isTab) {
    if (!isTab) {
      return null;
    }
    final isDelayTesting = ref.watch(currentGroupDelayTestingProvider);
    return IconButtonData(
      glyph: AppGlyphs.bolt,
      onPressed: () {
        _proxiesTabKey.currentState?.delayTestCurrentGroup();
      },
      tooltip: context.appLocalizations.delayTest,
      isLoading: isDelayTesting,
    );
  }

  void _onSearch(String value) {
    ref.read(queryProvider(QueryTag.proxies).notifier).value = value;
  }

  @override
  void initState() {
    super.initState();
    ref.listenManual(
      proxiesStyleSettingProvider.select(
        (state) => state.type == ProxiesType.tab,
      ),
      (prev, next) {
        if (prev != next) {
          setState(() {
            _isTab = next;
          });
        }
      },
      fireImmediately: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final isLoading = ref.watch(loadingProvider(LoadingTag.proxies));
    final picker = widget.picker;
    final isMobile = ViewScope.isMobileOf(context);
    final isTab = _isTab || isMobile;
    final primaryAction = _buildPrimaryAction(isTab);
    return CommonScaffold(
      isLoading: isLoading,
      resizeToAvoidBottomInset: false,
      backgroundColor: isMobile
          ? context.colorScheme.surfaceContainerLowest
          : null,
      primaryAction: primaryAction,
      searchActions: [?primaryAction],
      iconActions: [
        if (isTab && !picker && !isMobile)
          IconButtonData(
            glyph: AppGlyphs.locate,
            onPressed: () {
              _proxiesTabKey.currentState?.scrollToGroupSelected();
            },
            tooltip: context.appLocalizations.scrollToSelected,
          ),
      ],
      menuItems: picker ? const [] : _buildMenuItems(context),
      title: context.appLocalizations.proxies,
      searchState: AppBarSearchState(onSearch: _onSearch),
      body: Builder(
        builder: (context) {
          final body = isTab ? _tabView : const ProxiesListView();
          if (picker) {
            return body;
          }
          return _ConnectArea(child: body);
        },
      ),
    );
  }
}

/// The list over NekoBox's foot: the connect button alone while stopped,
/// riding the top edge of the stats bar that slides up while running.
class _ConnectArea extends ConsumerWidget {
  const _ConnectArea({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isStart = ref.watch(isStartProvider);
    final duration = context.motionDuration(kThemeAnimationDuration);
    final fabBottom = isStart
        ? _StatsBar.height - _ConnectFab.size / 2
        : _ConnectFab.margin;
    return BottomInsetScope(
      inset:
          BottomInsetScope.of(context) +
          (isStart
              ? _StatsBar.height + _ConnectFab.size / 2 + _ConnectFab.margin
              : _ConnectFab.clearance),
      child: Stack(
        children: [
          Positioned.fill(child: child),
          PositionedDirectional(
            start: 0,
            end: 0,
            bottom: 0,
            child: AnimatedSlide(
              offset: isStart ? Offset.zero : const Offset(0, 1),
              duration: duration,
              curve: Curves.easeOutCubic,
              child: isStart ? const _StatsBar() : const SizedBox.shrink(),
            ),
          ),
          AnimatedPositionedDirectional(
            start: 0,
            end: 0,
            bottom: fabBottom,
            duration: duration,
            curve: Curves.easeOutCubic,
            child: const Center(child: _ConnectFab()),
          ),
        ],
      ),
    );
  }
}

/// NekoBox's StatsBar: upload and download speed, and a status line that
/// tests the connection through the first group when tapped.
class _StatsBar extends ConsumerWidget {
  const _StatsBar();

  static const height = 96.0;

  Group? _firstGroup(WidgetRef ref) {
    final groups = ref.watch(currentGroupsStateProvider).value;
    return groups.isEmpty ? null : groups.first;
  }

  void _test(WidgetRef ref, Group group) {
    ref
        .read(proxiesActionProvider.notifier)
        .proxyDelayTest(
          Proxy(name: group.name, type: group.type.name),
          group.testUrl,
        );
  }

  String _status(BuildContext context, WidgetRef ref, Group? group) {
    final appLocalizations = context.appLocalizations;
    if (group == null) {
      return appLocalizations.connectedTapToTest;
    }
    final phase = ref.watch(
      delayTestPhaseProvider(proxyName: group.name, testUrl: group.testUrl),
    );
    if (phase != null) {
      return appLocalizations.connectionTesting;
    }
    final delay = ref.watch(
      delayProvider(proxyName: group.name, testUrl: group.testUrl),
    );
    if (delay == null) {
      return appLocalizations.connectedTapToTest;
    }
    return delay > 0
        ? appLocalizations.connectionTestSuccess(delay)
        : appLocalizations.connectionTestFailed(
            delayFailureText(delay, appLocalizations),
          );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colorScheme = context.colorScheme;
    final onPrimary = colorScheme.onPrimary;
    final traffic = ref.watch(
      trafficsProvider.select((state) => state.list.safeLast(const Traffic())),
    );
    final group = _firstGroup(ref);
    final speedStyle = AppTextStyle.footnote
        .of(context)
        .copyWith(color: onPrimary);
    return Material(
      color: colorScheme.primary,
      elevation: 8,
      child: InkWell(
        onTap: group == null ? null : () => _test(ref, group),
        child: SizedBox(
          height: height,
          width: double.infinity,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('▲  ${traffic.up.shortTraffic.show}/s', style: speedStyle),
                Text(
                  '▼  ${traffic.down.shortTraffic.show}/s',
                  style: speedStyle,
                ),
                Text(
                  _status(context, ref, group),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTextStyle.callout
                      .of(context)
                      .copyWith(color: onPrimary),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Starts and stops the tunnel from the proxy list, where NekoBox keeps it.
class _ConnectFab extends ConsumerWidget {
  const _ConnectFab();

  static const size = 56.0;
  static const margin = 16.0;
  static const clearance = size + margin * 2;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appLocalizations = context.appLocalizations;
    final colorScheme = context.colorScheme;
    final hasProfile = ref.watch(
      profilesProvider.select((state) => state.isNotEmpty),
    );
    final isStart = ref.watch(isStartProvider);
    return FloatingActionButton(
      heroTag: null,
      tooltip: isStart ? appLocalizations.stop : appLocalizations.start,
      backgroundColor: hasProfile
          ? colorScheme.primary
          : colorScheme.surfaceContainerHighest,
      foregroundColor: hasProfile
          ? colorScheme.onPrimary
          : colorScheme.onSurfaceVariant,
      shape: AppShape.circle,
      onPressed: hasProfile
          ? () => ref.read(commonActionProvider.notifier).toggleRunning()
          : null,
      child: AnimatedSwitcher(
        duration: context.motionDuration(kThemeAnimationDuration),
        child: _ServiceIcon(
          key: ValueKey(isStart),
          running: isStart,
          color: hasProfile
              ? colorScheme.onPrimary
              : colorScheme.onSurfaceVariant,
        ),
      ),
    );
  }
}

/// NekoBox's paper plane from `ic_service_idle.xml`, struck through while the
/// tunnel is down, on its 24 dp viewport.
class _ServiceIcon extends StatelessWidget {
  const _ServiceIcon({super.key, required this.running, required this.color});

  final bool running;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: const Size.square(24),
      painter: _ServiceIconPainter(running: running, color: color),
    );
  }
}

class _ServiceIconPainter extends CustomPainter {
  _ServiceIconPainter({required this.running, required this.color});

  static final _plane = _parse(
    'M17.68,9l-1.59,7L12.7,14.89l5-5.93M10,10.08l-3.57,3L5,12.55l5-2.47'
    'M21.25,2.28L0,12.8l6.83,2.57,9.76-8.21L9.26,15.89l8.29,2.67,3.7-16.27'
    'h0ZM9.45 17.56 L9.46 22 L12.09 18.41 L9.45 17.56 Z',
  );
  static final _strike = _parse('M19.73 22 L21 20.73 L3.27 3 L2 4.27 Z');
  static final _strikeGap = _parse(
    'M4.54 1.73 L3.27 3 L21 20.73 L22.27 19.46 Z',
  );

  final bool running;
  final Color color;

  static Path _parse(String data) {
    final writer = _PathWriter();
    writeSvgPathDataToPath(data, writer);
    return writer.path;
  }

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color;
    canvas.scale(size.shortestSide / 24);
    if (running) {
      canvas.drawPath(_plane, paint);
      return;
    }
    canvas
      ..save()
      ..clipPath(
        Path.combine(
          PathOperation.difference,
          Path()..addRect(const Rect.fromLTWH(0, 0, 24, 24)),
          _strikeGap,
        ),
      )
      ..drawPath(_plane, paint)
      ..restore()
      ..drawPath(_strike, paint);
  }

  @override
  bool shouldRepaint(_ServiceIconPainter oldDelegate) =>
      running != oldDelegate.running || color != oldDelegate.color;
}

class _PathWriter implements PathProxy {
  final path = Path();

  @override
  void moveTo(double x, double y) => path.moveTo(x, y);

  @override
  void lineTo(double x, double y) => path.lineTo(x, y);

  @override
  void cubicTo(
    double x1,
    double y1,
    double x2,
    double y2,
    double x3,
    double y3,
  ) => path.cubicTo(x1, y1, x2, y2, x3, y3);

  @override
  void close() => path.close();
}
