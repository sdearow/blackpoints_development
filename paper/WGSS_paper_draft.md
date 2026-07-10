# Who Gets Safe Streets? An Open-Source Spatial Decision Support System for Equity-Aware Road Safety Planning

> **Draft** — Introduction, Literature Review, Methodology.
> Results, Discussion and Conclusions to follow once intervention dates
> are consolidated. Citations marked ⚠ need verification/completion
> before submission.

**Keywords:** road safety; transport equity; spatial decision support
system; Vision Zero; Empirical Bayes; facility location; distributive
justice; Rome.

---

## Abstract

Road safety planning remains largely reactive and efficiency-driven:
interventions concentrate where crashes have already occurred, and
equity—when considered at all—is treated as a post-hoc academic analysis
rather than a criterion embedded in the planning process itself. This
paper presents an open-source Spatial Decision Support System (SDSS)
that closes the road safety policy loop—monitoring, risk diagnosis,
prescription, and evaluation—within a single interactive, reproducible
environment, and elevates distributive equity to a first-class design
criterion. The system builds on a georeferenced crash database and
network model, using Empirical Bayes Safety Performance Functions to
estimate crash risk while correcting for regression to the mean. Risk is
combined with a spatial need index that integrates social vulnerability
from census data to identify where intervention is most warranted.
Distributive equity is quantified in real time through Lorenz/Gini
measures, a concentration index, and bivariate LISA cluster analysis,
exposing spatial mismatches between need and provision as equity
priority zones. A multi-objective facility-location module (Maximal
Covering Location Problem) then proposes intervention locations, with an
interactive slider that makes the efficiency–equity trade-off explicit
and negotiable along a Pareto frontier. A before-after module evaluates
realised interventions using Empirical Bayes methods. We demonstrate the
system on the city of Rome, integrating municipal crash records, TomTom
flow and speed data, the PGTU functional road classification, 2021
census microdata, and the city's database of safety and active-mobility
projects. The tool bridges the gap between operational road safety
instruments and transport equity research, offering planners a
transparent, open, and participatory basis for asking not only *where*
to make streets safer, but *for whom*.

---

## 1. Introduction

Road traffic injury remains one of the most severe and most unequally
distributed public health burdens of urban life. Globally, road crashes
kill approximately 1.19 million people per year (WHO, 2023); in the
European Union, despite three decades of improvement, progress has
slowed markedly against the target of halving deaths by 2030 (European
Commission, 2019 ⚠). Italy records roughly three thousand road deaths
annually (ISTAT-ACI, 2023 ⚠), and Rome consistently reports the highest
absolute toll among Italian cities. The policy response, codified in the
*Safe System* and *Vision Zero* frameworks (Tingvall & Haworth, 1999;
Belin et al., 2012), reframes serious road trauma as a preventable
system failure rather than an inevitable by-product of mobility, and
places the protection of vulnerable road users at the centre of network
design.

Two persistent gaps separate this policy ambition from planning
practice. The first is **methodological**: despite a mature statistical
literature, everyday prioritisation in most municipalities remains
*reactive*, targeting locations with high recent crash counts. Because
severe crashes are rare and strongly overdispersed, naive rankings are
dominated by random fluctuation and regression to the mean (Hauer,
1997), and interventions chase noise as much as risk. The state of the
art—Safety Performance Functions with Empirical Bayes correction
(AASHTO, 2010), systemic risk screening (FHWA, 2013), High Injury
Networks (Vision Zero cities such as New York and San Francisco ⚠)—is
well established in research and in a handful of leading agencies, but
rarely packaged in tools that mid-sized administrations can adopt,
inspect, and re-run.

The second gap is **distributive**. A growing transport-justice
literature documents that both the burden of road danger and the
benefits of safety investment are socially patterned: children, older
adults, low-income households and residents of deprived neighbourhoods
face systematically higher exposure and injury risk (Lucas, 2012;
Karner et al., 2020; van Wee & Geurs, 2011 ⚠). Yet in planning practice
equity typically enters, if at all, as a retrospective evaluation
performed by researchers on decisions already taken. It is seldom
available *inside* the tools with which decisions are made, at the
moment they are made. The predictable result—documented across
contexts—is that visible, articulate, already-advantaged neighbourhoods
capture a disproportionate share of traffic-calming and public-realm
investment, while high-need areas wait.

This paper argues that the two gaps share a single practical solution:
embedding both state-of-the-art risk estimation *and* distributive
equity, as first-class and simultaneously visible criteria, in an
open-source Planning/Spatial Decision Support System (PSS/SDSS) that
municipal staff can actually operate. Our contribution is not any single
method—each component draws on established literature—but their
**integration into a closed policy loop** within one interactive,
reproducible environment:

1. **Monitoring.** A georeferenced crash database (470k+ records) is
   matched to a segmented network model derived from commercial floating
   car data and the municipal functional road classification.
2. **Diagnosis.** Negative binomial Safety Performance Functions and
   Empirical Bayes estimation yield stabilised excess-risk estimates;
   a High Injury Network and network-constrained kernel density
   estimation summarise where harm concentrates. In parallel, a census
   based social-vulnerability index and an intervention-provision layer
   feed distributive-equity statistics (Gini, concentration index,
   bivariate LISA) computed interactively, exposing *equity priority
   zones* where need is high and provision low.
3. **Prescription.** A Maximal Covering Location Problem allocates a
   budget of interventions over the network. Its demand function blends
   crash risk and social vulnerability through a single weight
   parameter, surfaced in the interface as an *efficiency ↔ equity*
   slider whose consequences are displayed on a pre-computed Pareto
   frontier—making the trade-off explicit, quantified, and negotiable.
4. **Evaluation.** Realised interventions are assessed with the
   Empirical Bayes before-after method (Hauer, 1997), closing the loop
   by feeding effectiveness evidence back into diagnosis and
   prescription.

We instantiate the system on Rome, Italy—a city of 2.75 million
residents, 5,240 km of classified network, and an actively growing
database of 2,677 safety and active-mobility projects across thirteen
intervention types. Three research questions structure the empirical
application:

- **RQ1 (concentration of harm).** How concentrated is severe road harm
  on the urban network, and can a stable High Injury Network be
  identified from Empirical Bayes-corrected estimates?
- **RQ2 (equity of provision).** Are existing and planned safety
  interventions distributed according to need—defined as the combination
  of crash risk and social vulnerability—or do they favour already
  advantaged areas?
- **RQ3 (efficiency–equity trade-off).** When intervention siting is
  optimised, how steep is the trade-off between covering maximum risk
  and covering maximum social vulnerability, and can it be made
  legible to decision-makers?

The paper proceeds as follows. Section 2 positions the work within four
literatures—crash risk modelling, transport equity, spatial
optimisation, and planning support systems—and identifies the
integration gap. Section 3 details the methodology of each module and
its implementation. Section 4 reports results for Rome; Section 5
discusses implications, limitations and transferability; Section 6
concludes. *(Sections 4–6 to be completed.)*

---

## 2. Literature review

### 2.1 From reactive hotspots to systemic risk estimation

The identification of hazardous road locations has moved through three
generations. First-generation *black spot* analysis ranks sites by
observed crash counts; its flaws—instability of rare-event counts,
selection bias, regression to the mean (RTM)—have been documented at
length (Hauer, 1997; Elvik, 2007 ⚠). Second-generation methods model
expected crash frequency as a function of exposure and site
characteristics through Safety Performance Functions (SPFs), typically
negative binomial regressions, and combine model predictions with
observed counts via Empirical Bayes (EB) weighting; the EB estimate
shrinks noisy observations toward the model expectation in proportion
to overdispersion, correcting RTM and enabling *excess-crash* ranking
(Hauer et al., 2002 ⚠; AASHTO, 2010). Severity is commonly incorporated
through Equivalent Property Damage Only (EPDO) weighting or separate
severity models.

Third-generation *systemic* approaches invert the logic: rather than
waiting for crashes to accumulate, they map risk factors across the
entire network (FHWA, 2013). Two spatial instruments are prominent in
practice. The **High Injury Network (HIN)**—the minimal share of street
length concentrating a large majority of deaths and serious
injuries—has become the organising map of Vision Zero programmes in
North American cities ⚠, though published implementations vary widely in
method and rarely stabilise counts with EB estimates. **Network
constrained kernel density estimation (NKDE)** respects the fact that
crashes occur on a 1-dimensional network embedded in 2-dimensional
space: planar KDE systematically over-smooths across parallel streets,
whereas network KDE distributes kernel mass along the graph (Okabe et
al., 2009; Xie & Yan, 2008; Okabe & Sugihara, 2012).

### 2.2 Transport equity: concepts and measurement

Transport equity scholarship distinguishes *horizontal* equity (like
treatment of like individuals) from *vertical* equity (prioritising
those with greater need or lesser ability), and distributive from
procedural justice (Litman, 2002/2023 ⚠). The social-exclusion strand
(Lucas, 2012) and the transport-justice strand (Martens, 2016; Karner
et al., 2020; Pereira et al., 2017) converge on the position that
transport investment should be evaluated against the distribution of
its benefits across social groups, not only against aggregate
efficiency. Road *safety* equity has received comparatively less
attention than accessibility equity, despite consistent evidence of
steep social gradients in pedestrian and child casualty risk ⚠.

Methodologically, the field borrows measurement instruments from
welfare and health economics. The **Lorenz curve and Gini index**
summarise how unequally a good (here: safety provision) is distributed
across a population. The **concentration index** (Wagstaff, Paci &
van Doorslaer, 1991), computed against a ranking by need rather than by
the good itself, captures *vertical* equity: a negative index indicates
concentration of provision among low-need units. Its weighted
computation via fractional ranks follows Lerman & Yitzhaki (1989).
Spatially, **local indicators of spatial association** (Anselin, 1995)
and their bivariate extension identify statistically significant
clusters where one variable (need) is high while the neighbourhood
value of another (provision) is low—an explicitly spatial mismatch
measure. Composite indices of social vulnerability raise well-known
construction issues—normalisation, weighting, aggregation—for which the
OECD handbook provides standard guidance (Nardo et al., 2008), and all
areal analysis is subject to the Modifiable Areal Unit Problem
(Openshaw, 1984) and the ecological fallacy.

### 2.3 Locating interventions: spatial optimisation with equity

Where to place a limited budget of facilities is the classic terrain of
location science. The **Maximal Covering Location Problem** (Church &
ReVelle, 1974) maximises demand covered within a service radius given a
fixed number of facilities; together with the p-median (Hakimi, 1964)
and set-covering (Toregas et al., 1971) formulations it anchors a vast
literature (ReVelle & Eiselt, 2005). Equity has long been discussed in
facility location—typically as minimax criteria, equality constraints,
or Rawlsian objectives ⚠—and multi-objective formulations tracing
efficiency–equity Pareto frontiers are well established technically,
including evolutionary approaches (Deb et al., 2002). Applications to
*road safety* facilities (speed cameras, traffic calming, crossings)
exist but are scarce, and we are aware of none in which the
efficiency–equity weight is exposed as an interactive control inside a
planning tool, with the frontier pre-computed for immediate
exploration. This is precisely the gap our prescription module fills.

### 2.4 Evaluating what was built

Credible evaluation of safety interventions must confront RTM, secular
trends and confounding. The observational standard is the **Empirical
Bayes before-after** design (Hauer, 1997), which predicts the
counterfactual "after" frequency at treated sites from SPFs and
before-period EB estimates, yielding an unbiased effectiveness index
θ (the empirical Crash Modification Factor) with tractable variance;
it underpins the CMF Clearinghouse ⚠ and the HSM (AASHTO, 2010).
Complementary designs include comparison-group methods, interrupted
time series (Bernal, Cummins & Gasparrini, 2017), Bayesian structural
time-series counterfactuals (Brodersen et al., 2015), and area-wide
studies such as the London 20 mph zones evaluation (Grundy et al.,
2009). Almost universally, these are one-off *ex post* studies produced
outside the planning environment; embedding a continuously updated EB
evaluation layer in the same tool that prioritises and sites
interventions is, to our knowledge, novel in the published literature.

### 2.5 Planning support systems and the implementation gap

Planning Support Systems—geo-information instruments dedicated to
supporting specific planning tasks (Geertman & Stillwell, 2004,
2009)—have long promised evidence-based, participatory decision
processes, and have long under-delivered: documented bottlenecks
include poor task–tool fit, opacity, cost, and the gulf between
academic prototypes and operational practice (Vonk, Geertman &
Schot, 2005; te Brömmelstroet, 2013 ⚠). Recent reviews emphasise
transparency, immediate responsiveness, and open licensing as adoption
conditions ⚠. Road safety PSS specifically remain rare; commercial
crash-analysis suites cover diagnosis but neither distributive equity
nor prescriptive optimisation, and are closed-source. Our design
responds directly to this literature: fully open code and data
pipeline, single-command reproducibility, pre-computation of expensive
analytics so that interaction is instantaneous, and explicit surfacing
of value trade-offs rather than their burial in technical defaults.

### 2.6 Synthesis of the gap

Each ingredient of the present system—EB risk estimation, HIN/NKDE
screening, concentration-index equity analysis, MCLP siting, EB
before-after evaluation—stands on mature literature. What is missing,
and what this paper contributes, is (i) their **integration into a
single closed-loop, open-source planning environment**; (ii) the
treatment of **vertical equity as a first-class, interactive criterion**
of both diagnosis and prescription, rather than a retrospective academic
exercise; and (iii) an empirical demonstration on a major European
capital, quantifying both the distributive state of current provision
(RQ2) and the marginal price of equity in optimised siting (RQ3).

---

## 3. Methodology

### 3.1 Framework architecture

The system implements the policy loop of Figure 1 *(to be drawn)*:
monitoring feeds diagnosis; diagnosis (risk and equity) feeds
prescription; realised interventions are evaluated; evaluation evidence
updates diagnosis. Each stage is a deterministic, configuration-driven
step of a Python pipeline (steps `s00`–`s10`), writing versioned
geospatial outputs consumed by an interactive dashboard (Dash/Plotly,
eight views). All parameters—thresholds, weights, radii, time
windows—reside in a single configuration file; every stochastic
component is seeded. The full stack is open source (GeoPandas, PySAL,
statsmodels, PuLP), and the analysis reproduces end-to-end with one
command. Heavy analytics (spatial statistics, optimisation frontiers)
are pre-computed in the pipeline so that all dashboard interaction is
effectively instantaneous—a deliberate response to the PSS usability
literature (§2.5).

### 3.2 Study area and data

**Study area.** Rome, Italy (Roma Capitale): 2,749,031 residents (2021
census) across 23,591 census enumeration areas (14,757 inhabited), and
a classified urban network of 5,243 km.

**Crash data.** The municipal georeferenced crash registry, 2004–2025
(473,466 records after deduplication), with severity recoded to three
levels (fatal / injury / property-damage-only; the source does not
distinguish serious from slight injuries—a declared limitation),
timestamps, and a geocoding-quality flag. The primary analysis window
matches the SPF calibration period (2018–2021).

**Network and exposure.** A commercial floating-car dataset (TomTom,
~94,000 arcs) provides directed geometry, average daily traffic and
speed percentiles per arc; the municipal 2026 Functional Classification
(PGTU) is spatially joined to assign road hierarchy; signalised
junctions come from the municipal registry (with a measured systematic
offset correction).

**Socio-demographics.** The 2021 Italian census at enumeration-area
level supplies population, age structure, citizenship, educational
attainment and employment. Income is not published at this scale;
education and non-employment serve as socio-economic proxies (declared
limitation, tested in sensitivity analysis).

**Interventions.** The municipal project database—*a living database,
by design*—currently 2,677 interventions in 13 types (speed enforcement
sites, environmental islands/30 km/h zones, school streets, pedestrian
areas, cycle network and GRAB, cycle-pedestrian bridges, LTZ gates and
perimeters, point/linear/areal works, project districts), ingested from
16 heterogeneous sources through a configuration registry. Each
intervention carries a normalised phase, a content-based stable
identifier (geometry hash), an influence radius by type, and an
activation date; dates are progressively confirmed through an override
table, and all analyses degrade gracefully (flagging non-evaluable
items) where dates are provisional.

### 3.3 Network risk estimation

**Segmentation and matching.** Junction nodes are extracted from arc
topology (degree ≥ 3), filtered for false intersections (separate
carriageways, bifurcations) and clustered by proximity and toponym,
yielding 6,693 junctions; arcs between junctions are chained into
61,931 homogeneous segments (same toponym and hierarchy, traffic
variation below threshold, length 100–2,000 m). Crashes are assigned to
junctions (25 m buffer) or snapped to segments (30 m geometric
threshold, 100 m with fuzzy toponym match), with match-quality flags.

**Safety Performance Functions.** For segments, per functional class
(classes pooled below 50 sites):

  E[Y] = exp(β₀ + β₁ ln AADT + β₂ ln L) · t        (NB2)

with observation years t as offset; junction SPFs use total entering
flow. Overdispersion k is retained per model. Diagnostics include CURE
plots and information criteria.

**Empirical Bayes and severity weighting.** For each site i,

  w_i = 1/(1 + k·E_i),  EB_i = w_i E_i + (1−w_i) O_i,
  excess_i = EB_i − E_i,

with EPDO severity weights (12/3/1 for fatal/injury/PDO, reflecting the
three-level severity coding) applied through the site's observed
severity mix to obtain excess_EPDO_i, and social cost via national
unit values.

**High Injury Network.** Sites are ranked by KSI density per kilometre,
stabilised by the EB ratio (KSI_i · EB_i/O_i); the HIN is the top of
the ranking whose cumulative KSI share reaches a configurable coverage
threshold (70% in the base case). The concentration curve (share of
network vs share of KSI) is reported in full.

**Network KDE.** Segments are cut into 20 m lixels; crash mass
(EPDO-weighted; junction-matched crashes re-snapped to the nearest
segment within 50 m) is spread along the curvilinear abscissa with a
quartic kernel (bandwidth 200 m). The kernel does not cross junctions
in the present implementation—an intra-segment approximation of full
network KDE, declared and to be tested in bandwidth sensitivity.

### 3.4 Distributive equity module

**Unit of analysis.** The census enumeration area (inhabited units
only, n = 14,757). MAUP sensitivity at a second scale is planned
(§3.8).

**Social vulnerability.** Five indicators—share of children (0–14),
of elderly (65+), of foreign residents, of low educational attainment
(at most lower-secondary, base 9+), of non-employed (15–64)—are
normalised to 0–100 by robust percentile scaling and combined by
weighted mean. Three alternative weighting schemes (equal;
age-focused; deprivation-focused) constitute the sensitivity set.

**Risk at area level.** Site-level excess_EPDO is apportioned to areas
by intersected segment length (point junctions by containment), scaled
to density per km², and normalised zero-inflated to 0–100.

**Need.** need_i = √(vulnerability_i · risk_i) (geometric mean:
vertical-equity reading, both dimensions required), with a weighted
arithmetic alternative in configuration.

**Provision.** An intervention *serves* an area if its influence
footprint (type-specific buffer for points; geometry for lines and
polygons) intersects it; provision counts are computed in total and by
type, optionally filtered by intervention phase (crucial while the
project database consolidates: unfiltered provision measures the
*project pipeline*, not the built environment—results are labelled
accordingly).

**Equity statistics.** (i) Population-weighted Lorenz curve and Gini
index of per-capita provision. (ii) Concentration index of provision
against the need ranking, with population weights via fractional ranks
(Lerman & Yitzhaki, 1989); CI < 0 denotes pro-advantaged distribution.
Because one intervention type (the cycle network) dominates counts, the
mean of per-type CIs is reported alongside the total. (iii) Bivariate
local Moran statistics (need vs neighbourhood provision; k-nearest
neighbour weights, 999 conditional permutations, fixed seed) classify
areas into H/L quadrants with pseudo-significance. (iv) A 3×3
zero-inflated bivariate classification (zeros always in class 1;
positive terciles) drives the map legend. **Equity priority zones** are
areas in the high-need/low-provision cell or in significant High–Low
LISA clusters. All indices recompute interactively under type and
stratum filters in the dashboard.

### 3.5 Equity-aware intervention siting

**Formulation.** Given demand points i (inhabited areas with positive
risk or vulnerability; representative points), candidate sites j, and
binary coverage a_ij = 1 iff d(i,j) ≤ r (r = 500 m base case), the MCLP

  max Σ_i d_i y_i   s.t.  y_i ≤ Σ_{j∈N_i} x_j,  Σ_j x_j ≤ p,
  x_j, y_i ∈ {0,1}

is solved for budget p (20 in the base case). The demand blends the two
objectives through the equity weight w ∈ [0,1]:

  d_i(w) = (1−w)·risk_i + w·vulnerability_i .

Vulnerability—not the composite need—is used deliberately: need embeds
risk by construction, which collapses the two objectives and flattens
the frontier (verified empirically; reported as a design finding).

**Candidates.** The union of (a) the top sites by excess_EPDO and (b)
sites with positive expected frequency inside equity priority zones.
Set (b) is essential: without it, vulnerable areas lacking crash
history are unreachable even at w = 1, since interventions must lie on
the network.

**Solution and frontier.** The base solver is greedy maximisation
(classical (1−1/e) guarantee; near-optimal on spatial instances and
validated against the exact CBC integer-programming solver on instances
with known optima). The Pareto frontier is pre-computed for
w = 0, 0.1, …, 1 (seconds on the full Rome instance) and stored; the
dashboard slider selects among stored scenarios, so no optimisation
ever runs at interaction time. Reported per scenario: share of
city-wide risk covered, share of vulnerability covered, residents
covered, and residents of equity priority zones covered.

**Declared simplifications.** Binary coverage (no distance decay),
Euclidean radius, type-agnostic facilities, maximisation of reached
demand rather than expected crash reduction (the coupling with
evaluated effectiveness is the object of the evaluation module).

### 3.6 Before-after evaluation

For every intervention, treated sites are the network sites
intersecting its influence footprint. Before/after windows (3 and 2
years around the activation date, truncated to crash-data availability;
minimum 24/12 effective months) define per-site observed counts O and
SPF expectations E scaled by effective years. Following Hauer (1997):

  w_s = 1/(1+k E_pre,s);  EB_pre,s = w_s E_pre,s + (1−w_s) O_pre,s;
  π_s = EB_pre,s · (E_post,s/E_pre,s);
  Var(π_s) = (E_post,s/E_pre,s)² · EB_pre,s (1−w_s);

summing over treated sites, the effectiveness index and its variance:

  θ = (O_post/π) / (1 + Var(π)/π²);
  Var(θ) = θ² (1/O_post + Var(π)/π²) / (1 + Var(π)/π²)² ,

with a Poisson upper bound when O_post = 0. θ < 1 indicates a crash
reduction attributable to the intervention (an empirical CMF). The
module is *evaluability-aware*: interventions with provisional
(placeholder) dates or insufficient post-period data are flagged with
explicit reasons rather than dropped, and enter estimation
automatically as dates are confirmed—an operational requirement of a
living project database. Comparison-group and interrupted-time-series
designs (Bernal et al., 2017) are specified as robustness extensions
for the first date-confirmed case studies; a further declared caveat is
partial contamination of the SPF baseline by interventions realised
within the calibration window.

### 3.7 Implementation, openness, reproducibility

~9,000 lines of Python across eleven pipeline steps and the dashboard;
226 automated tests, including hand-computed statistical cases (EB
before-after; Gini/CI limiting cases; MCLP instances with known
optima); configuration-only extension of the intervention registry; all
randomised procedures seeded; code and derived open-format outputs
version-controlled. The system runs on commodity hardware; the complete
Rome pipeline executes in under one hour, of which the crash–network
matching dominates.

### 3.8 Methodological cautions

We declare, and where possible quantify, the following: MAUP (second
spatial scale in preparation; all equity results currently at
enumeration-area scale); ecological inference limits (area-level
indicators do not license individual-level claims); proxy nature of the
socio-economic indicators in the absence of small-area income data;
under-reporting of pedestrian and cycling crashes, which biases both
risk and equity layers against active-travel areas; the
project-pipeline (rather than as-built) nature of the current provision
layer, pending phase consolidation; intra-segment NKDE; binary-coverage
MCLP; and constant-over-time SPF expectations in the evaluation module.

---

*Sections 4 (Results), 5 (Discussion) and 6 (Conclusions) will be
drafted once intervention dates begin to consolidate; preliminary
results for RQ1–RQ3 are available in the project reports.*

## References (to consolidate — ⚠ items need verification)

- AASHTO (2010). *Highway Safety Manual*. Washington, DC.
- Anselin, L. (1995). Local Indicators of Spatial Association—LISA.
  *Geographical Analysis*, 27(2), 93–115.
- Belin, M.-Å., Tillgren, P., & Vedung, E. (2012). Vision Zero – a road
  safety policy innovation. *International Journal of Injury Control
  and Safety Promotion*, 19(2), 171–179.
- Bernal, J. L., Cummins, S., & Gasparrini, A. (2017). Interrupted time
  series regression for the evaluation of public health interventions.
  *International Journal of Epidemiology*, 46(1), 348–355.
- Brodersen, K. H., et al. (2015). Inferring causal impact using
  Bayesian structural time-series models. *Annals of Applied
  Statistics*, 9(1), 247–274.
- Church, R., & ReVelle, C. (1974). The maximal covering location
  problem. *Papers of the Regional Science Association*, 32, 101–118.
- Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). A fast and
  elitist multiobjective genetic algorithm: NSGA-II. *IEEE Transactions
  on Evolutionary Computation*, 6(2), 182–197.
- FHWA (2013). *Systemic Safety Project Selection Tool*. FHWA-SA-13-019.
- Geertman, S., & Stillwell, J. (2004). Planning support systems: an
  inventory of current practice. *Computers, Environment and Urban
  Systems*, 28(4), 291–310.
- Grundy, C., et al. (2009). Effect of 20 mph traffic speed zones on
  road injuries in London, 1986–2006. *BMJ*, 339, b4469.
- Hakimi, S. L. (1964). Optimum locations of switching centers.
  *Operations Research*, 12(3), 450–459.
- Hauer, E. (1997). *Observational Before-After Studies in Road
  Safety*. Pergamon.
- Karner, A., London, J., Rowangould, D., & Manaugh, K. (2020). From
  transportation equity to transportation justice. *Journal of Planning
  Literature*, 35(4), 440–459.
- Lerman, R. I., & Yitzhaki, S. (1989). Improving the accuracy of
  estimates of Gini coefficients. *Journal of Econometrics*, 42(1).
- Litman, T. (2023 ⚠). *Evaluating Transportation Equity*. VTPI.
- Lucas, K. (2012). Transport and social exclusion: Where are we now?
  *Transport Policy*, 20, 105–113.
- Martens, K. (2016). *Transport Justice: Designing Fair Transportation
  Systems*. Routledge.
- Nardo, M., et al. (2008). *Handbook on Constructing Composite
  Indicators*. OECD/JRC.
- Okabe, A., Satoh, T., & Sugihara, K. (2009). A kernel density
  estimation method for networks. *IJGIS*, 23(1), 7–32.
- Okabe, A., & Sugihara, K. (2012). *Spatial Analysis Along Networks*.
  Wiley.
- Openshaw, S. (1984). *The Modifiable Areal Unit Problem*. GeoBooks.
- Pereira, R. H. M., Schwanen, T., & Banister, D. (2017). Distributive
  justice and equity in transportation. *Transport Reviews*, 37(2).
- ReVelle, C., & Eiselt, H. A. (2005). Location analysis: a synthesis
  and survey. *EJOR*, 165(1), 1–19.
- Tingvall, C., & Haworth, N. (1999). Vision Zero: an ethical approach
  to safety and mobility. *6th ITE International Conference*.
- Toregas, C., et al. (1971). The location of emergency service
  facilities. *Operations Research*, 19(6), 1363–1373.
- Vonk, G., Geertman, S., & Schot, P. (2005). Bottlenecks blocking
  widespread usage of planning support systems. *Environment and
  Planning A*, 37(5), 909–924.
- Wagstaff, A., Paci, P., & van Doorslaer, E. (1991). On the
  measurement of inequalities in health. *Social Science & Medicine*,
  33(5), 545–557.
- WHO (2023). *Global Status Report on Road Safety 2023*. Geneva.
- Xie, Z., & Yan, J. (2008). Kernel density estimation of traffic
  accidents in a network space. *Computers, Environment and Urban
  Systems*, 32(5), 396–406.
