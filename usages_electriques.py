"""Ventilations pédagogiques uniquement : aucun détail Enedis mesuré."""
import numpy as np
import plotly.graph_objects as go
USAGES = {'chauffage':'Chauffage électrique','ecs':'Eau chaude électrique','refroidissement':'Refroidissement','eclairage':'Éclairage','auxiliaires':'Auxiliaires'}
APPAREILS = {'refrigerateur':'Réfrigérateur','lave_linge':'Lave-linge','lave_vaisselle':'Lave-vaisselle','four':'Four électrique','plaques_cuisson':'Plaques électriques','seche_linge':'Sèche-linge','autres_appareils':'Autres appareils'}
COLONNES_DETAIL = ['conso_'+k+'_scenario_kwh' for k in list(USAGES)+list(APPAREILS)]

def figures_usages(q, unite='kwh'):
    base=q.loc[q.donnee_simulee].dropna(subset=COLONNES_DETAIL)
    left,right=go.Figure(),go.Figure()
    unit='kWh/m²/an' if unite=='m2' else 'kWh/logement/an'
    if base.empty:
        for f in [left,right]:
            f.add_annotation(text='Détail disponible uniquement dans les données simulées.',showarrow=False)
            f.update_xaxes(visible=False);f.update_yaxes(visible=False)
    else:
        for prefix,suffix,name,color,pattern in [('conso_dpe_','_kwh','DPE simulé','#246BB0','/'),('conso_','_scenario_kwh','Usages simulés','#E59842','')]:
            cols=[prefix+k+suffix for k in USAGES]
            vals=base[cols].mean().to_numpy()
            left.add_trace(go.Bar(y=list(USAGES.values()),x=vals,orientation='h',name=name,
                marker=dict(color=color,pattern_shape=pattern),text=[f'{v:,.0f}' for v in vals],textposition='auto',
                hovertemplate='%{y}<br>%{x:.1f} '+unit+'<extra>'+name+'</extra>'))
        cols=['conso_'+k+'_scenario_kwh' for k in APPAREILS]
        for typ,color,pattern in [('appartement','#246BB0','/'),('maison','#E59842','')]:
            b=base.loc[base.type_logement.eq(typ)]
            if b.empty:continue
            vals=b[cols].mean().to_numpy()
            parts=b[cols].sum().to_numpy()/b.conso_enedis_unifiee_kwh.sum()*100
            right.add_trace(go.Bar(y=list(APPAREILS.values()),x=vals,orientation='h',name=typ.capitalize(),
                marker=dict(color=color,pattern_shape=pattern),customdata=np.c_[parts,np.repeat(len(b),len(cols))],
                text=[f'{v:,.0f}' for v in vals],textposition='auto',
                hovertemplate='%{y}<br>Moyenne : %{x:.1f} '+unit+'<br>Part du total sélectionné : %{customdata[0]:.1f} %<br>%{customdata[1]:.0f} données simulées<extra>'+typ+'</extra>'))
    for f in [left,right]:
        f.update_layout(template='plotly_white',barmode='group',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family='Arial',size=14,color='#273A50'),margin=dict(l=115,r=15,t=60,b=40),
            legend=dict(orientation='h',y=1.02,x=0,font=dict(size=9)))
        f.update_yaxes(autorange='reversed',automargin=True,tickfont=dict(size=14),title_font=dict(size=14))
        f.update_xaxes(title=unit,rangemode='tozero',tickfont=dict(size=14),title_font=dict(size=14))
    return left,right
