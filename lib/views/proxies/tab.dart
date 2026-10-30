import 'dart:async';
import 'dart:math';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/common.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'card.dart';
import 'common.dart';
import 'group_tabs.dart';

class ProxiesTabView extends ConsumerStatefulWidget {
  const ProxiesTabView({super.key});

  static Map<String, PageStorageKey> pageListStoreMap = {};

  @override
  ConsumerState<ProxiesTabView> createState() => ProxiesTabViewState();
}

class ProxiesTabViewState extends ConsumerState<ProxiesTabView>
    with TickerProviderStateMixin {
  TabController? _tabController;
  final Map<String, ScrollController> _scrollControllers = {};
  int _columns = 1;

  @override
  void initState() {
    super.initState();
    ref.listenManual(proxiesTabControllerStateProvider, (prev, next) {
      if (prev == next) {
        return;
      }
      if (!stringListEquality.equals(prev?.groupNames, next.groupNames)) {
        final groupNames = next.groupNames;
        final currentGroupName = next.currentGroupName;
        final index = groupNames.indexWhere((item) => item == currentGroupName);
        _updateTabController(groupNames.length, index);
      }
    }, fireImmediately: true);
  }

  @override
  void dispose() {
    _destroyTabController();
    for (final controller in _scrollControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  ScrollController _scrollControllerOf(String groupName) {
    return _scrollControllers.putIfAbsent(
      groupName,
      () => sheetScrollController(context),
    );
  }

  // The page of a dropped group still holds its controller until this frame
  // unmounts it.
  void _pruneScrollControllers(List<Group> groups) {
    final names = {for (final group in groups) group.name};
    final dropped = [
      for (final entry in _scrollControllers.entries)
        if (!names.contains(entry.key)) entry,
    ];
    for (final entry in dropped) {
      _scrollControllers.remove(entry.key);
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => entry.value.dispose(),
      );
    }
  }

  void scrollToGroupSelected() {
    final group = currentGroup;
    final controller = _scrollControllers[group?.name];
    if (group == null || controller == null) {
      return;
    }
    final cardType = _cardTypeOf(
      ref.read(proxiesTabStateProvider).proxyCardType,
    );
    final rowOffset = selectedRowOffset(
      proxies: group.all,
      selectedProxyName: ref.read(selectedProxyNameProvider(group.name)),
      columns: _columns,
      rowExtent: getRowExtent(cardType),
    );
    if (rowOffset == null) {
      return;
    }
    animateScrollTo(controller, rowOffset);
  }

  // NekoBox's list keeps every node to one line of name on a phone.
  ProxyCardType _cardTypeOf(ProxyCardType setting) =>
      ViewScope.isMobileOf(context) ? ProxyCardType.compact : setting;

  Future<void> delayTestCurrentGroup() async {
    final group = currentGroup;
    if (group == null) {
      return;
    }
    await ref
        .read(proxiesActionProvider.notifier)
        .delayTestPageGroup(group.name);
  }

  Group? get currentGroup {
    return _getGroup(_tabController?.index);
  }

  Group? _getGroup(int? index) {
    final groups = ref.read(proxiesTabStateProvider).groups;
    if (index == null || index < 0 || index >= groups.length) {
      return null;
    }
    return groups[index];
  }

  void _tabControllerListener([int? index]) {
    final group = _getGroup(index ?? _tabController?.index);
    if (group == null) {
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      ref
          .read(proxiesActionProvider.notifier)
          .updateCurrentGroupName(group.name);
    });
  }

  void _destroyTabController() {
    _tabController?.removeListener(_tabControllerListener);
    _tabController?.dispose();
    _tabController = null;
  }

  // An empty group list keeps the previous controller: the outgoing tab bar
  // still drives it while the empty state animates in.
  void _updateTabController(int length, int index) {
    if (length == 0) {
      return;
    }
    _destroyTabController();
    final realIndex = index == -1 ? 0 : index;
    final controller = TabController(
      length: length,
      initialIndex: realIndex,
      vsync: this,
    );
    _tabController = controller;
    _tabControllerListener(realIndex);
    controller.addListener(_tabControllerListener);
  }

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    ref.watch(themeSettingProvider.select((state) => state.textScale));
    final groups = ref.watch(
      proxiesTabStateProvider.select((state) => state.groups),
    );
    final isMobile = ViewScope.isMobileOf(context);
    final cardType = isMobile
        ? ProxyCardType.compact
        : ref.watch(
            proxiesTabStateProvider.select((state) => state.proxyCardType),
          );
    final proxiesLayout = ref.watch(
      proxiesStyleSettingProvider.select((state) => state.layout),
    );
    final isSearching = ref.watch(
      queryProvider(
        QueryTag.proxies,
      ).select((query) => SearchQuery(query).isNotEmpty),
    );
    _pruneScrollControllers(groups);
    final controller = _tabController;
    return NullStatusSwitcher(
      isEmpty: groups.isEmpty || controller == null,
      isSearching: isSearching,
      nullStatus: NullStatus(
        illustration: NullStatusIllustration.proxies,
        label: appLocalizations.nullTip(appLocalizations.proxies),
      ),
      child: controller == null
          ? const SizedBox.shrink()
          : AppBarClearance(
              child: Column(
                children: [
                  if (isMobile)
                    _GroupTabBar(controller: controller, groups: groups)
                  else
                    Padding(
                      padding: const EdgeInsets.only(top: 4, bottom: 16),
                      child: GroupTabs(controller: controller, groups: groups),
                    ),
                  Expanded(
                    child: WidthBuilder(
                      builder: (_, width) {
                        final columns = ViewScope.isMobileOf(context)
                            ? 1
                            : getProxiesColumns(
                                max(width - 32, 0),
                                proxiesLayout,
                              );
                        _columns = columns;
                        return TabBarView(
                          controller: controller,
                          children: [
                            for (final group in groups)
                              ProxyGroupView(
                                key: ValueKey(group.name),
                                controller: _scrollControllerOf(group.name),
                                group: group,
                                columns: columns,
                                cardType: cardType,
                              ),
                          ],
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

/// The groups as NekoBox lays them out on a phone: a strip of tabs in the
/// bar's fill, right under it.
class _GroupTabBar extends StatelessWidget {
  const _GroupTabBar({required this.controller, required this.groups});

  final TabController controller;
  final List<Group> groups;

  @override
  Widget build(BuildContext context) {
    final colorScheme = context.colorScheme;
    final onPrimary = colorScheme.onPrimary;
    return ColoredBox(
      color: colorScheme.primary,
      child: TabBar(
        controller: controller,
        isScrollable: true,
        tabAlignment: TabAlignment.start,
        dividerColor: Colors.transparent,
        labelColor: onPrimary,
        unselectedLabelColor: onPrimary.withValues(alpha: 0.7),
        labelStyle: AppTextStyle.subheadline.of(context, emphasized: true),
        unselectedLabelStyle: AppTextStyle.subheadline.of(context),
        indicatorSize: TabBarIndicatorSize.label,
        indicator: UnderlineTabIndicator(
          borderSide: BorderSide(color: onPrimary, width: 2),
        ),
        tabs: [
          for (final group in groups)
            Tab(child: EmojiText(group.name, maxLines: 1)),
        ],
      ),
    );
  }
}

class ProxyGroupView extends ConsumerWidget {
  final Group group;
  final ScrollController controller;
  final int columns;
  final ProxyCardType cardType;

  const ProxyGroupView({
    super.key,
    required this.group,
    required this.controller,
    required this.columns,
    required this.cardType,
  });

  PageStorageKey _getPageStorageKey(WidgetRef ref) {
    final profile = ref.read(currentProfileProvider);
    final key =
        '${profile?.id}_${ScrollPositionCacheKey.proxiesTabList.name}_${group.name}';
    return ProxiesTabView.pageListStoreMap.updateCacheValue(
      key,
      () => PageStorageKey(key),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final proxies = group.all;
    final inset = ViewScope.isMobileOf(context) ? 8.0 : 16.0;
    return CommonScrollBar(
      controller: controller,
      thumbVisibility: true,
      child: GridView.builder(
        key: _getPageStorageKey(ref),
        controller: controller,
        padding: EdgeInsets.only(
          left: inset,
          right: inset,
          top: ViewScope.isMobileOf(context) ? inset : 0,
          bottom: 16 + BottomInsetScope.of(context),
        ),
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: columns,
          mainAxisSpacing: proxyGridSpacing,
          crossAxisSpacing: 8,
          mainAxisExtent: getItemHeight(cardType),
        ),
        itemCount: proxies.length,
        addAutomaticKeepAlives: false,
        itemBuilder: (_, index) {
          final proxy = proxies[index];
          return ProxyCard(
            testUrl: group.testUrl,
            groupType: group.type,
            type: cardType,
            proxy: proxy,
            groupName: group.name,
          );
        },
      ),
    );
  }
}
