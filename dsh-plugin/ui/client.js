// Native DSH 0.1.5-rc.2 client bundle facade; no extra bundler or React copy.
window.__ModuleLoader__.load({id: 'asuna-ui-elements-v1', factory: (require) => {
  const {createElement} = require('react');
  return {
    inject: ['slots', 'layout'],
    apply(ctx) {
      ctx.slots.inject('main', () => ctx.slots.register({name: 'main', key: 'asuna'}, () =>
        createElement('iframe', {src: '/asuna/', title: 'Asuna UI Elements V1', style: {width: '100%', height: '100%', border: 0, background: '#fff'}})));
      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({name: 'sidebar.panellist', id: 'asuna', label: 'Asuna', order: 0}, () => createElement('span', null, 'A')));
    },
  };
}});
